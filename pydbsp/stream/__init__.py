import sys
from abc import abstractmethod
from types import NotImplementedType
from typing import Callable, Generic, Iterator, List, Optional, Protocol, TypeVar, cast

from pydbsp.core import AbelianGroupOperation

T = TypeVar("T")

INFINITY = sys.maxsize


class Stream(Generic[T]):
    """
    Represents a stream of elements from an Abelian group.
    """

    timestamp: int
    inner: List[T]
    group_op: AbelianGroupOperation[T]
    identity: bool

    def __init__(self, group_op: AbelianGroupOperation[T]) -> None:
        self.inner = []
        self.group_op = group_op
        self.timestamp = -1
        self.identity = True
        self.send(group_op.identity())

    def send(self, element: T) -> None:
        """Adds an element to the stream and increments the timestamp."""
        id = self.group().identity()
        if element != id:
            self.identity = False

        self.inner.append(element)
        self.timestamp += 1

    def group(self) -> AbelianGroupOperation[T]:
        """Returns the Abelian group operation associated with this stream."""
        return self.group_op

    def current_time(self) -> int:
        """Returns the timestamp of the most recently arrived element."""
        return self.timestamp

    def __iter__(self) -> Iterator[T]:
        return self.inner.__iter__()

    def __repr__(self) -> str:
        return self.inner.__repr__()

    def __getitem__(self, timestamp: int) -> T:
        """Returns the element at the given timestamp."""
        if timestamp < 0:
            raise ValueError("Timestamp cannot be negative")

        if timestamp <= self.current_time():
            return self.inner.__getitem__(timestamp)

        elif timestamp > self.current_time():
            id = self.group().identity()
            while timestamp > self.current_time():
                self.send(id)

        return self.__getitem__(timestamp)

    def latest(self) -> T:
        """Returns the most recent element."""
        return self.__getitem__(self.current_time())

    def is_identity(self) -> bool:
        return self.identity

    def __eq__(self, other: object) -> bool | NotImplementedType:
        """
        Compares this stream with another, considering all timestamps up to the latest.
        """
        if not isinstance(other, Stream):
            return NotImplemented

        if self.is_identity() and other.is_identity():
            return True

        cast(Stream[T], other)

        self_timestamp = self.current_time()
        other_timestamp = other.current_time()

        if self_timestamp != other_timestamp:
            return False

        return self.inner == other.inner  # type: ignore


StreamReference = Callable[[], Stream[T]]


class StreamHandle(Generic[T]):
    """A handle to a stream, allowing lazy access."""

    ref: StreamReference[T]

    def __init__(self, stream_reference: StreamReference[T]) -> None:
        self.ref = stream_reference

    def get(self) -> Stream[T]:
        """Returns the referenced stream."""
        return self.ref()


R = TypeVar("R")


class Operator(Protocol[T]):
    @abstractmethod
    def step(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def output_handle(self) -> StreamHandle[T]:
        raise NotImplementedError


def step_until_fixpoint[T](operator: Operator[T]) -> None:
    while not operator.step():
        pass


def step_until_fixpoint_and_return[T](operator: Operator[T]) -> Stream[T]:
    step_until_fixpoint(operator)

    return operator.output_handle().get()


class UnaryOperator(Operator[R], Protocol[T, R]):
    """Base class for stream operators with a single input and output."""

    input_stream_handle: StreamHandle[T]
    output_stream_handle: StreamHandle[R]

    def __init__(
        self,
        stream_handle: Optional[StreamHandle[T]],
        output_stream_group: Optional[AbelianGroupOperation[R]],
    ) -> None:
        if stream_handle is not None:
            self.set_input(stream_handle, output_stream_group)

    def set_input(
        self,
        stream_handle: StreamHandle[T],
        output_stream_group: Optional[AbelianGroupOperation[R]],
    ) -> None:
        """Sets the input stream and initializes the output stream."""
        self.input_stream_handle = stream_handle

        if output_stream_group is not None:
            output = Stream(output_stream_group)

            self.output_stream_handle = StreamHandle(lambda: output)
        else:
            output = cast(Stream[R], Stream(self.input_a().group()))

            self.output_stream_handle = StreamHandle(lambda: output)

    def output(self) -> Stream[R]:
        return self.output_stream_handle.get()

    def input_a(self) -> Stream[T]:
        return self.input_stream_handle.get()

    def output_handle(self) -> StreamHandle[R]:
        handle = StreamHandle(lambda: self.output())

        return handle


S = TypeVar("S")


class BinaryOperator(Operator[S], Protocol[T, R, S]):
    """Base class for stream operators with two inputs and one output."""

    input_stream_handle_a: StreamHandle[T]
    input_stream_handle_b: StreamHandle[R]
    output_stream_handle: StreamHandle[S]

    def __init__(
        self,
        stream_a: Optional[StreamHandle[T]],
        stream_b: Optional[StreamHandle[R]],
        output_stream_group: Optional[AbelianGroupOperation[S]],
    ) -> None:
        if stream_a is not None:
            self.set_input_a(stream_a)

        if stream_b is not None:
            self.set_input_b(stream_b)

        if output_stream_group is not None:
            output = Stream(output_stream_group)

            self.set_output_stream(StreamHandle(lambda: output))

    def set_input_a(self, stream_handle_a: StreamHandle[T]) -> None:
        """Sets the first input stream and initializes the output stream."""
        self.input_stream_handle_a = stream_handle_a
        output = cast(Stream[S], Stream(self.input_a().group()))

        self.set_output_stream(StreamHandle(lambda: output))

    def set_input_b(self, stream_handle_b: StreamHandle[R]) -> None:
        """Sets the second input stream."""
        self.input_stream_handle_b = stream_handle_b

    def set_output_stream(self, output_stream_handle: StreamHandle[S]) -> None:
        """Sets the output stream handle."""
        self.output_stream_handle = output_stream_handle

    def output(self) -> Stream[S]:
        return self.output_stream_handle.get()

    def input_a(self) -> Stream[T]:
        return self.input_stream_handle_a.get()

    def input_b(self) -> Stream[R]:
        return self.input_stream_handle_b.get()

    def output_handle(self) -> StreamHandle[S]:
        handle = StreamHandle(lambda: self.output())

        return handle


F1 = Callable[[T], R]


class Lift1(UnaryOperator[T, R]):
    """Lifts a unary function to operate on a stream."""

    f1: F1[T, R]

    def __init__(
        self,
        stream: Optional[StreamHandle[T]],
        f1: F1[T, R],
        output_stream_group: Optional[AbelianGroupOperation[R]],
    ):
        self.f1 = f1
        super().__init__(stream, output_stream_group)

    def step(self) -> bool:
        """Applies the lifted function to the next element in the input stream."""
        output_timestamp = self.output().current_time()
        input_timestamp = self.input_a().current_time()
        if output_timestamp < input_timestamp:
            self.output().send(self.f1(self.input_a()[output_timestamp + 1]))

            return False

        return True


F2 = Callable[[T, R], S]


class Lift2(BinaryOperator[T, R, S]):
    """Lifts a binary function to operate on two streams where data arrives at
    different times."""

    def __init__(
        self,
        stream_a: Optional[StreamHandle[T]],
        stream_b: Optional[StreamHandle[R]],
        f2: F2[T, R, S],
        output_stream_group: Optional[AbelianGroupOperation[S]],
    ) -> None:
        self.f2 = f2

        super().__init__(stream_a, stream_b, output_stream_group)

    def step(self) -> bool:
        """Applies the lifted function to the most recently arrived elements in both input streams."""
        a_timestamp = self.input_a().current_time()
        b_timestamp = self.input_b().current_time()
        output_timestamp = self.output().current_time()
        join = max(a_timestamp, b_timestamp)
        fixedpoint = False
        if output_timestamp == join:
            fixedpoint = True

            return fixedpoint

        a = self.input_a()[output_timestamp + 1]
        b = self.input_b()[output_timestamp + 1]

        application = self.f2(a, b)
        self.output().send(application)

        return fixedpoint


class LiftedGroupAdd(Lift2[T, T, T]):
    def __init__(self, stream_a: StreamHandle[T], stream_b: Optional[StreamHandle[T]]):
        super().__init__(
            stream_a,
            stream_b,
            lambda x, y: stream_a.get().group().add(x, y),
            None,
        )


class LiftedGroupNegate(Lift1[T, T]):
    def __init__(self, stream: StreamHandle[T]):
        super().__init__(stream, lambda x: stream.get().group().neg(x), None)


class StreamAddition(AbelianGroupOperation[Stream[T]]):
    """Defines addition for streams by lifting their underlying group's addition."""

    group: AbelianGroupOperation[T]

    def __init__(self, group: AbelianGroupOperation[T]) -> None:
        self.group = group

    def add(self, a: Stream[T], b: Stream[T]) -> Stream[T]:
        """Adds two streams element-wise."""
        handle_a = StreamHandle(lambda: a)
        handle_b = StreamHandle(lambda: b)

        lifted_group_add = LiftedGroupAdd(handle_a, handle_b)

        return step_until_fixpoint_and_return(lifted_group_add)

    def inner_group(self) -> AbelianGroupOperation[T]:
        """Returns the underlying group operation."""
        return self.group

    def neg(self, a: Stream[T]) -> Stream[T]:
        """Negates a stream element-wise."""
        handle_a = StreamHandle(lambda: a)
        lifted_group_neg = LiftedGroupNegate(handle_a)

        return step_until_fixpoint_and_return(lifted_group_neg)

    def identity(self) -> Stream[T]:
        """
        Returns an identity stream for the addition operation.
        """
        identity_stream = Stream(self.group)

        return identity_stream
