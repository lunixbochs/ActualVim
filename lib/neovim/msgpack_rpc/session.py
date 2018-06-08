"""Synchronous msgpack-rpc session layer."""
from collections import deque
from queue import Queue
import threading
import traceback

class Session(object):

    """Msgpack-rpc session layer that uses coroutines for a synchronous API.

    This class provides the public msgpack-rpc API required by this library.
    It uses the greenlet module to handle requests and notifications coming
    from Nvim with a synchronous API.
    """

    def __init__(self, async_session):
        """Wrap `async_session` on a synchronous msgpack-rpc interface."""
        self._async_session = async_session
        self._request_cb = self._notification_cb = None
        self._pending_messages = deque()
        self._is_running = False
        self._setup_exception = None
        self._lock = threading.RLock()

        self._async_queue = Queue()
        thread = threading.Thread(target=self._async_worker)
        thread.daemon = True
        thread.start()

    def _async_worker(self):
        while True:
            job = self._async_queue.get()
            if job is None:
                return
            cb, args, kwargs = job
            try:
                cb(*args, **kwargs)
            except Exception:
                traceback.print_exc()

    def async_dispatch(self, fn, *args, **kwargs):
        self._async_queue.put((fn, args, kwargs))

    def threadsafe_call(self, fn, *args, **kwargs):
        """Wrapper around `AsyncSession.threadsafe_call`."""
        def async_wrapper():
            self.async_dispatch(fn, *args, **kwargs)
        self._async_session.threadsafe_call(async_wrapper)

    def next_message(self):
        """Block until a message(request or notification) is available.

        If any messages were previously enqueued, return the first in queue.
        If not, run the event loop until one is received.
        """
        if self._is_running:
            raise Exception('Event loop already running')
        if self._pending_messages:
            return self._pending_messages.popleft()
        self._async_session.run(self._enqueue_request_and_stop,
                                self._enqueue_notification_and_stop)
        if self._pending_messages:
            return self._pending_messages.popleft()

    def request(self, method, *args, **kwargs):
        """Send a msgpack-rpc request and block until as response is received.

        If the event loop is running, this method must have been called by a
        request or notification handler running on a greenlet. In that case,
        send the quest and yield to the parent greenlet until a response is
        available.

        When the event loop is not running, it will perform a blocking request
        like this:
        - Send the request
        - Run the loop until the response is available
        - Put requests/notifications received while waiting into a queue

        If the `async` flag is present and True, a asynchronous notification is
        sent instead. This will never block, and the return value or error is
        ignored.
        """
        with self._lock:
            async = kwargs.pop('async', False)
            if async:
                self._async_session.notify(method, args)
                return

            cb = kwargs.pop('cb', None)
            if cb:
                def indirect(*args, **kwargs):
                    self.threadsafe_call(cb, *args, **kwargs)
                self._async_session.request(method, args, indirect)
                if not self._is_running:
                    self._async_session.run(self._enqueue_request, self._enqueue_notification)
                return

            if kwargs:
                raise ValueError("request got unsupported keyword argument(s): {}"
                                 .format(', '.join(kwargs.keys())))

            if self._is_running:
                v = self._yielding_request(method, args, timeout=kwargs.pop('timeout', 0.25))
            else:
                v = self._blocking_request(method, args)

            if not v:
                # EOF
                raise IOError('EOF')
            err, rv = v
            if err:
                raise self.error_wrapper(err)
            return rv

    def run(self, request_cb, notification_cb, setup_cb=None):
        """Run the event loop to receive requests and notifications from Nvim.

        Like `AsyncSession.run()`, but `request_cb` and `notification_cb` are
        inside greenlets.
        """
        self._request_cb = request_cb
        self._notification_cb = notification_cb
        self._is_running = True
        self._setup_exception = None

        def on_setup():
            try:
                setup_cb()
            except Exception as e:
                self._setup_exception = e
                self.stop()

        if setup_cb:
            self.async_dispatch(on_setup)

        if self._setup_exception:
            error('Setup error: {}'.format(self._setup_exception))
            raise self._setup_exception

        # Process all pending requests and notifications
        while self._pending_messages:
            msg = self._pending_messages.popleft()
            getattr(self, '_on_{}'.format(msg[0]))(*msg[1:])
        self._async_session.run(self._on_request, self._on_notification)
        self._is_running = False
        self._request_cb = None
        self._notification_cb = None

        if self._setup_exception:
            raise self._setup_exception

    def stop(self):
        """Stop the event loop."""
        self._async_session.stop()

    def _yielding_request(self, method, args, timeout=None):
        q = Queue()

        def response_cb(err, rv):
            q.put((err, rv))

        self._async_session.request(method, args, response_cb)
        # FIXME timeout is to avoid hang
        return q.get(timeout=timeout)

    def _blocking_request(self, method, args):
        result = []

        def response_cb(err, rv):
            result.extend([err, rv])
            self.stop()

        self._async_session.request(method, args, response_cb)
        self._async_session.run(self._enqueue_request,
                                self._enqueue_notification)
        return result

    def _enqueue_request_and_stop(self, name, args, response):
        self._enqueue_request(name, args, response)
        self.stop()

    def _enqueue_notification_and_stop(self, name, args):
        self._enqueue_notification(name, args)
        self.stop()

    def _enqueue_request(self, name, args, response):
        self._pending_messages.append(('request', name, args, response,))

    def _enqueue_notification(self, name, args):
        self._pending_messages.append(('notification', name, args,))

    def _on_request(self, name, args, response):
        def handler():
            try:
                rv = self._request_cb(name, args)
                response.send(rv)
            except ErrorResponse as err:
                response.send(err.args[0], error=True)
            except Exception as err:
                response.send(repr(err) + "\n" + traceback.format_exc(5), error=True)

        self.async_dispatch(handler)

    def _on_notification(self, name, args):
        def handler():
            try:
                self._notification_cb(name, args)
            except Exception:
                pass

        self.async_dispatch(handler)


class ErrorResponse(BaseException):

    """Raise this in a request handler to respond with a given error message.

    Unlike when other exceptions are caught, this gives full control off the
    error response sent. When "ErrorResponse(msg)" is caught "msg" will be
    sent verbatim as the error response.No traceback will be appended.
    """

    pass
