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
import asyncore
import socket
import sys

__version__ = ".2"


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
