import io
import os
import platform
import sys

try:
    b64 = platform.architecture()[0] == '64bit'
    target = None
    if platform.system() == 'Windows':
        if b64:
            target = 'st3_windows_x64'
        else:
            target = 'st3_windows_x32'
    elif platform.system() == 'Darwin':
            target = 'st3_osx_x64'
    elif platform.system() == 'Linux':
        if b64:
            target = 'st3_linux_x64'
        else:
            target = 'st3_linux_x32'
    if target is None:
        raise ImportError

    here = os.path.dirname(__file__)
    sys.path.append(os.path.join(here, target))
    from msgpack import pack, packb, unpack, unpackb, Packer, Unpacker, ExtType as Ext
    sys.path.pop()
except ImportError as e:
    print('msgpack: warning, using slow fallback\n    {}'.format(e))
    from . import umsgpack
    from .umsgpack import pack, unpack, packb, unpackb, Ext

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
                    yield unpack(self.buf)
                except umsgpack.InsufficientDataException:
                    self.buf.seek(pos)
                    self.buf = io.BytesIO(self.buf.read())
                    raise StopIteration
