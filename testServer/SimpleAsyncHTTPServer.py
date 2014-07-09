#TODO: refactor to clean code and make tests
import asyncore
import os
import optparse
from ristretto.server.async_httpserver import Server
from ristretto.server.server_handlers import which


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