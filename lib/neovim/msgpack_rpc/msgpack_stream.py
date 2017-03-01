"""Msgpack handling in the event loop pipeline."""
from actualvim.lib import umsgpack
import io

from ..compat import unicode_errors_default

class Unpacker:
    def __init__(self):
        self.buf = io.BytesIO()

    def feed(self, data):
        # TODO: does this need to be thread safe?
        pos = self.buf.tell()
        self.buf.seek(0, io.SEEK_END)
        self.buf.write(data)
        self.buf.seek(pos)

    def __iter__(self):
        while True:
            try:
                pos = self.buf.tell()
                yield umsgpack.unpack(self.buf)
            except umsgpack.InsufficientDataException:
                self.buf.seek(pos)
                self.buf = io.BytesIO(self.buf.read())
                raise StopIteration


class MsgpackStream(object):

    """Two-way msgpack stream that wraps a event loop byte stream.

    This wraps the event loop interface for reading/writing bytes and
    exposes an interface for reading/writing msgpack documents.
    """

    def __init__(self, event_loop):
        """Wrap `event_loop` on a msgpack-aware interface."""
        self._event_loop = event_loop
        self._unpacker = Unpacker()
        self._message_cb = None

    def threadsafe_call(self, fn):
        """Wrapper around `BaseEventLoop.threadsafe_call`."""
        self._event_loop.threadsafe_call(fn)

    def send(self, msg):
        """Queue `msg` for sending to Nvim."""
        self._event_loop.send(umsgpack.packb(msg))

    def run(self, message_cb):
        """Run the event loop to receive messages from Nvim.

        While the event loop is running, `message_cb` will be called whenever
        a message has been successfully parsed from the input stream.
        """
        self._message_cb = message_cb
        self._event_loop.run(self._on_data)
        self._message_cb = None

    def stop(self):
        """Stop the event loop."""
        self._event_loop.stop()

    def _on_data(self, data):
        self._unpacker.feed(data)
        for msg in self._unpacker:
            self._message_cb(msg)
