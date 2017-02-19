"""Synchronous msgpack-rpc session layer."""
import logging
from collections import deque

from traceback import format_exc

# we don't have greenlet in st3
import threading
def spawn_thread(fn):
    t = threading.Thread(target=fn)
    t.daemon = True
    t.start()

logger = logging.getLogger(__name__)
error, debug, info, warn = (logger.error, logger.debug, logger.info,
                            logger.warning,)


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

    def threadsafe_call(self, fn, *args, **kwargs):
        """Wrapper around `AsyncSession.threadsafe_call`."""
        def handler():
            try:
                fn(*args, **kwargs)
            except Exception:
                warn("error caught while excecuting async callback\n%s\n",
                     format_exc())

        def greenlet_wrapper():
            spawn_thread(handler)

        self._async_session.threadsafe_call(greenlet_wrapper)

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
        async = kwargs.pop('async', False)
        if async:
            self._async_session.notify(method, args)
            return

        if kwargs:
            raise ValueError("request got unsupported keyword argument(s): {}"
                             .format(', '.join(kwargs.keys())))

        v = self._blocking_request(method, args)
        if not v:
            # EOF
            raise IOError('EOF')
        err, rv = v
        if err:
            info("'Received error: %s", err)
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
            spawn_thread(on_setup)

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
                debug('greenlet %s finished executing, ' +
                      'sending %s as response', gr, rv)
                response.send(rv)
            except ErrorResponse as err:
                warn("error response from request '%s %s': %s", name,
                     args, format_exc())
                response.send(err.args[0], error=True)
            except Exception as err:
                warn("error caught while processing request '%s %s': %s", name,
                     args, format_exc())
                response.send(repr(err) + "\n" + format_exc(5), error=True)
            debug('greenlet %s is now dying...', gr)

        # Create a new greenlet to handle the request
        spawn_thread(handler)
        debug('received rpc request, thread will handle it')

    def _on_notification(self, name, args):
        def handler():
            try:
                self._notification_cb(name, args)
                debug('greenlet %s finished executing', gr)
            except Exception:
                warn("error caught while processing notification '%s %s': %s",
                     name, args, format_exc())

            debug('greenlet %s is now dying...', gr)

        spawn_thread(handler)
        debug('received rpc notification, thread will handle it')


class ErrorResponse(BaseException):

    """Raise this in a request handler to respond with a given error message.

    Unlike when other exceptions are caught, this gives full control off the
    error response sent. When "ErrorResponse(msg)" is caught "msg" will be
    sent verbatim as the error response.No traceback will be appended.
    """

    pass
