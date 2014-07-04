"""
Get an updated version of this server from:
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/440665


Original pseudo-async* version by Pierre Quentel, available from
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/259148

* It would only be async while reading requests, it would switch to a
synchronous write to a socket when writing a response to a request to a
socket.  Ick.


Features this version offers:
1. Uses asynchronous reading and writing to/from sockets all the time.
2. Performs sectioned reads from on-disk files, allowing for serving files of
   unlimited size.
3. More informative logging.
4. A quick wrapper for logging to a file and stdout/stderr.
5. Trailing-slash redirects on directories.
6. Optional built-in favicon.ico (to reduce the number of spurious log
   entries).
7. Subclass which does not allow any directory lists or redirecting to
   /index.htm[l] .
8. Subclass which does not allow any directory lists, but does automatic
   redirection to /index.htm[l] .
9. Doesn't try to open reserved names on Windows.

For most people, one can run this from the command line and get a reasonably
functioning web server with minor issue.

I benchmarked this version in my personal projects folder, which contains
around a gig of files, sizes ranging from a few kilobytes, to 100 megabytes.
I then performed two concurrent "wget -m http://localhost/" calls (from
different paths) on Windows 2k (machine is a P4 2.8ghz with hyperthreading,
1.5 gigs memory, reading from an 80 gig SATA drive, writing to a 120 gig PATA
drive).

On small files, it was able to serve up 15-30 files/second. On larger (10+
meg) files, it was able to serve up at 15+ megs/second (so says adding the
speed reported by wget). The server never broke 7 megs of resident memory, and
tended to hang below 10% processor utilization.

There exists a live host running this web server: nada.ics.uci.edu
"""
#TODO: refactor to clean code and make tests
import codecs
import asynchat
import asyncore
import socket
import http.server
import sys
import cgi
import io
import os
import traceback
import zlib
import optparse
import urllib.parse
from collections import deque

__version__ = ".2"


def encode(s, name, *args, **kwargs):
    codec = codecs.lookup(name)
    print(codec)
    rv, length = codec.encode(s, *args, **kwargs)
    if not isinstance(rv, (str, bytes, bytearray)):
        raise TypeError('Not a string or byte codec')
    return rv


def popall(deque):
    #Preallocate the list to save memory resizing.
    r = len(deque) * [None]
    for i in range(len(r)):
        r[i] = deque.popleft()
    return r


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


class RequestHandler(asynchat.async_chat, http.server.SimpleHTTPRequestHandler):
    server_version = "SimpleAsyncHTTPServer/" + __version__
    protocol_version = "HTTP/1.1"
    blocksize = 4096

    #In enabling the use of buffer objects by setting use_buffer to True,
    #any data block sent will remain in memory until it has actually been
    #sent.
    use_buffer = False
    use_favicon = False

    def __init__(self, conn, addr, server):
        asynchat.async_chat.__init__(self, conn)
        self.client_address = addr
        self.connection = conn
        self.server = server
        # set the terminator : when it is received, this means that the
        # http request is complete ; control will be passed to
        # self.found_terminator
        self.set_terminator(bytes('\r\n\r\n', 'UTF-8'))
        self.incoming = deque()
        self.outgoing = deque()
        self.rfile = None
        self.wfile = writewrapper(self.outgoing, -self.use_buffer or self.blocksize)
        self.found_terminator = self.handle_request_line
        self.request_version = "HTTP/1.1"
        self.code = None
        # buffer the response and headers to avoid several calls to select()

    def collect_incoming_data(self, data):

        """Collect the data arriving on the connexion"""
        if not data:
            self.ac_in_buffer = ""
            return
        self.incoming.append(data)

    def prepare_POST(self):
        """Prepare to read the request body"""
        bytesToRead = int(self.headers.getheader('content-length'))
        # set terminator to length (will read bytesToRead bytes)
        self.set_terminator(bytesToRead)
        self.incoming.clear()
        # control will be passed to a new found_terminator
        self.found_terminator = self.handle_post_data

    def handle_post_data(self):
        """Called when a POST request body has been read"""
        self.rfile = io.BytesIO(b''.join(popall(self.incoming)))
        self.rfile.seek(0)
        self.do_POST()

    def do_GET(self):
        """Begins serving a GET request"""

        # Check for query string in URL
        qspos = self.path.find('?')
        if qspos >= 0:
            self.body = urllib.parse.parse_qs(self.path[qspos + 1:], keep_blank_values=1)
            self.path = self.path[:qspos]

        self.handle_data()

    def do_POST(self):
        """Begins serving a POST request. The request data must be readable
        on a file-like object called self.rfile"""
        ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        length = int(self.headers.getheader('content-length'))
        if ctype == 'multipart/form-data':
            self.body = cgi.parse_multipart(self.rfile, pdict)
        elif ctype == 'application/x-www-form-urlencoded':
            qs = self.rfile.read(length)
            self.body = urllib.parse.parse_qs(qs, keep_blank_values=1)
        else:
            self.body = ''                   # Unknown content-type
            #self.handle_post_body()
        self.handle_data()

    def handle_data(self):
        """Class to override"""
        if self.use_favicon and self.path == '/favicon.ico':
            self.send_response(200)
            self.send_header("Content-type", 'text/html')
            self.send_header("Content-Length", len(favicon))
            self.end_headers()
            self.log_request(self.code, len(favicon))
            self.outgoing.append(favicon)
            self.outgoing.append(None)
            return

        f = self.send_head()
        if f:
            # do some special things with file objects so that we don't have
            # to read them all into memory at the same time...may leave a
            # file handle open for longer than is really desired, but it does
            # make it able to handle files of unlimited size.
            self.log_request(self.code, os.fstat(f.fileno())[6])
            self.outgoing.append(f)
        else:
            self.log_request(self.code)

        # signal the end of this request
        self.outgoing.append(None)

    def handle_request_line(self):
        """Called when the http request line and headers have been received"""
        # prepare attributes needed in parse_request()
        self.rfile = io.BytesIO(b''.join(popall(self.incoming)))
        self.rfile.seek(0)
        self.raw_requestline = self.rfile.readline()
        self.parse_request()

        if self.command in ['GET', 'HEAD']:
            # if method is GET or HEAD, call do_GET or do_HEAD and finish
            method = "do_" + self.command
            if hasattr(self, method):
                getattr(self, method)()
        elif self.command == "POST":
            # if method is POST, call prepare_POST, don't finish yet
            self.prepare_POST()
        else:
            self.send_error(501, "Unsupported method (%s)" % self.command)

    def end_headers(self):
        """Send the blank line ending the MIME headers, send the buffered
        response and headers on the connection"""
        if self.request_version != 'HTTP/0.9':
            self.outgoing.append("\r\n")

    def handle_error(self):
        traceback.print_exc(file=sys.stderr)
        self.close()

    def writable(self):
        return len(self.outgoing) and self.connected

    def handle_write(self):
        O = self.outgoing
        while len(O):
            a = O.popleft()
            #handle end of request disconnection
            if a is None:
                #Some clients have issues with keep-alive connections, or
                #perhaps I implemented them wrong.

                #If the user is running a Python version < 2.4.1, there is a
                #bug with SimpleHTTPServer:
                #    http://python.org/sf/1097597
                #So we should be closing anyways, even though the client will
                #claim a partial download, so as to prevent hung-connections.
                ## if self.close_connection:
                self.close()
                return
            #handle file objects
            elif hasattr(a, 'read'):
                _a, a = a, a.read(self.blocksize)
                if not a:
                    del _a
                    continue
                else:
                    O.appendleft(_a)
                    break
            #handle string/buffer objects
            elif len(a):
                break
        else:
            #if we get here, the outgoing deque is empty
            return
            #if we get here, 'a' is a string or buffer object of length > 0
        try:
            if isinstance(a, bytes):
                a = codecs.decode(a)
            if isinstance(a, str):
                a = encode(a, 'utf-8')
            print('Encoded Data: ', a)
            num_sent = self.send(a)
            if num_sent < len(a):
                if not num_sent:
                    # this is probably overkill, but it can save the
                    # allocations of buffers when they are enabled
                    O.appendleft(a)
                elif self.use_buffer:
                    O.appendleft(memoryview(a, num_sent))
                else:
                    O.appendleft(a[num_sent:])

        except socket.error as why:
            if isinstance(why, str):
                self.log_error(why)
            elif isinstance(why, tuple) and isinstance(why[-1], str):
                self.log_error(why[-1])
            else:
                self.log_error(str(why))
            self.handle_error()

    def send_head(self):
        path = self.translate_path(self.path)
        if sys.platform == 'win32':
            if os.path.split(path)[1].lower().split('.')[0] in deque.reserved_names:
                self.send_error(404, "File not found")
                return
        if os.path.isdir(path):
            if not self.path.endswith('/'):
                self.send_response(302)
                x = '<META HTTP-EQUIV="refresh" CONTENT="0;URL=%s/">' % self.path
                self.send_header("Content-Location", self.path + '/')
                self.send_header("Content-Length", len(x))
                self.end_headers()
                self.wfile.write(x)
                return None
        return http.server.SimpleHTTPRequestHandler.send_head(self)

    def send_response(self, code, message=None):
        if self.code:
            return
        self.code = code
        if message is None:
            if code in self.responses:
                message = self.responses[code][0]
            else:
                message = ''
        if self.request_version != 'HTTP/0.9':
            self.wfile.write("%s %d %s\r\n" %
                             (self.protocol_version, code, message))
            # print (self.protocol_version, code, message)
        self.send_header('Server', self.version_string())
        self.send_header('Date', self.date_time_string())

    def log_message(self, format, *args):
        sys.stderr.write("%s - - [%s] %s \"%s\" \"%s\"\n" %
                         (self.address_string(),
                          self.log_date_time_string(),
                          format % args,
                          self.headers.get('referer', ''),
                          self.headers.get('user-agent', '')
                         ))

        #


class OnlyExactFiles(RequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            self.send_error(404, "File not found")
            return None
        return RequestHandler.send_head(self)

        #


class ExactFilesAndIndex(RequestHandler):
    def list_directory(self, path):
        self.send_error(404, "File not found")
        return None

        #


class Server(asyncore.dispatcher):
    def __init__(self, ip, port, handler):
        self.ip = ip
        self.port = port
        self.handler = handler
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

        self.set_reuse_addr()
        self.bind((ip, port))

        # Quoting the socket module documentation...
        # listen(backlog)
        #     Listen for connections made to the socket. The backlog argument
        #     specifies the maximum number of queued connections and should
        #     be at least 1; the maximum value is system-dependent (usually
        #     5).
        self.listen(5)

    def handle_accept(self):
        try:
            conn, addr = self.accept()
        except socket.error:
            self.log_info('warning: server accept() threw an exception', 'warning')
            return
        except TypeError:
            self.log_info('warning: server accept() threw EWOULDBLOCK', 'warning')
            return
            # creates an instance of the handler class to handle the request/response
        # on the incoming connexion
        self.handler(conn, addr, self)


favicon = None

which = (RequestHandler, OnlyExactFiles, ExactFilesAndIndex)


class to_logfile:
    if 1:
        fl = True

    def __init__(self, fileobj):
        self.f = fileobj

    def write(self, data):
        data = data.encode('utf-8')
        sys.__stdout__.write(data)
        self.f.write(data)
        if self.fl:
            self.f.flush()


if __name__ == "__main__":
    usage = "usage: \%prog -r<root> [-p<port>] [-0|-1|-2]"

    parser = optparse.OptionParser(usage)
    parser.add_option('-r', '--root', dest='root',
                      help='Root path of the web server', action='store')
    parser.add_option('-p', '--port', dest='port', type='int',
                      help='Port to listen on (default 80)', default=80, action='store')
    parser.add_option('-0', dest='server', help='Run the standard server (default)',
                      action='store_const', const=0, default=0)
    parser.add_option('-1', dest='server',
                      help='Run the server which only serves exact file names specified',
                      action='store_const', const=1)
    parser.add_option('-2', dest='server',
                      help='Run the server which will serve exact files and directory->index files',
                      action='store_const', const=2)

    options, args = parser.parse_args()

    if options.root is None:
        parser.error("Need root path to start server")

    if not os.path.isdir(options.root):
        parser.error("Root path does not exist")

    os.chdir(options.root)

    req_handler = which[options.server]
    s = Server('', options.port, req_handler)
    print((req_handler.__name__, "running on port", options.port, "with root path", options.root))
    asyncore.loop()