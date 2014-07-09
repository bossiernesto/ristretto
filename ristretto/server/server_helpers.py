import codecs

def encode(s, name, *args, **kwargs):
    codec = codecs.lookup(name)
    rv, length = codec.encode(s, *args, **kwargs)
    if not isinstance(rv, (str, bytes, bytearray)):
        raise TypeError('Not a string or byte codec')
    return rv

class writewrapper(object):
    def __init__(self, d, blocksize=4096):
        self.blocksize = blocksize
        self.d = d

    def write(self, data):
        if self.blocksize in (None, -1):
            self.d.append(data)
        else:
            BS = self.blocksize
            xtra = 0
            if len(data) % BS:
                xtra = len(data) % BS + BS
            buf = self.d
            for i in range(0, len(data) - xtra, BS):
                buf.append(data[i:i + BS])
            if xtra:
                buf.append(data[-xtra:])