import http.server
import asynchat
from ristretto.utils.util import popall
from .async_httpserver import __version__
from .server_helpers import *
import io
import sys
import traceback
import os
import cgi
import urllib
import socket
from collections import deque


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


favicon = None

which = (RequestHandler, OnlyExactFiles, ExactFilesAndIndex)