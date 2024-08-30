from typing import Optional, TypeVar

from pydbsp.stream import (
    Lift1,
    LiftedGroupAdd,
    LiftedGroupNegate,
    Stream,
    StreamAddition,
    StreamHandle,
    UnaryOperator,
    step_until_timestamp_and_return,
)
from pydbsp.stream.functions.linear import stream_elimination, stream_introduction

T = TypeVar("T")


class Delay(UnaryOperator[T, T]):
    def __init__(self, stream: Optional[StreamHandle[T]]) -> None:
        super().__init__(stream, None)

    def step(self) -> bool:
        output_timestamp = self.output().current_time()

        delayed_value = self.input_a()[output_timestamp]

        self.output().send(delayed_value)
        if output_timestamp == -1:
            return self.step()

        return True


class Differentiate(UnaryOperator[T, T]):
    delayed_stream: Delay[T]
    delayed_negated_stream: LiftedGroupNegate[T]
    differentiation_stream: LiftedGroupAdd[T]

    def __init__(self, stream: StreamHandle[T]) -> None:
        self.input_stream_handle = stream
        self.delayed_stream = Delay(self.input_stream_handle)
        self.delayed_negated_stream = LiftedGroupNegate(self.delayed_stream.output_handle())
        self.differentiation_stream = LiftedGroupAdd(
            self.input_stream_handle, self.delayed_negated_stream.output_handle()
        )
        self.output_stream_handle = self.differentiation_stream.output_handle()

    def step(self) -> bool:
        self.delayed_stream.step()
        self.delayed_negated_stream.step()

        return self.differentiation_stream.step()


class Integrate(UnaryOperator[T, T]):
    delayed_stream: Delay[T]
    integration_stream: LiftedGroupAdd[T]

    def __init__(self, stream: StreamHandle[T]) -> None:
        self.input_stream_handle = stream
        self.integration_stream = LiftedGroupAdd(self.input_stream_handle, None)
        self.delayed_stream = Delay(self.integration_stream.output_handle())
        self.integration_stream.set_input_b(self.delayed_stream.output_handle())

        self.output_stream_handle = self.integration_stream.output_handle()

    def step(self) -> bool:
        self.integration_stream.step()

        return self.delayed_stream.step()


class LiftedDelay(Lift1[Stream[T], Stream[T]]):
    def __init__(self, stream: StreamHandle[Stream[T]]):
        super().__init__(
            stream,
            lambda s: step_until_timestamp_and_return(Delay(StreamHandle(lambda: s)), s.current_time() + 1),
            None,
        )


class LiftedIntegrate(Lift1[Stream[T], Stream[T]]):
    def __init__(self, stream: StreamHandle[Stream[T]]):
        super().__init__(
            stream,
            lambda s: step_until_timestamp_and_return(Integrate(StreamHandle(lambda: s)), s.current_time()),
            None,
        )


class LiftedDifferentiate(Lift1[Stream[T], Stream[T]]):
    def __init__(self, stream: StreamHandle[Stream[T]]):
        super().__init__(
            stream,
            lambda s: step_until_timestamp_and_return(Differentiate(StreamHandle(lambda: s)), s.current_time()),
            None,
        )


class LiftedStreamIntroduction(Lift1[T, Stream[T]]):
    def __init__(self, stream: StreamHandle[T]) -> None:
        super().__init__(
            stream,
            lambda x: stream_introduction(x, stream.get().group()),
            StreamAddition(stream.get().group()),  # type: ignore
        )


class LiftedStreamElimination(Lift1[Stream[T], T]):
    def __init__(self, stream: StreamHandle[Stream[T]]) -> None:
        super().__init__(stream, lambda x: stream_elimination(x), stream.get().group().inner_group())  # type: ignore