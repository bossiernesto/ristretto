"""
    Simple http client to be used for testing purposes on the test server of ristretto.
"""
import http.client
import logging


class Client(object):
    def __init__(self, server='localhost:5000'):
        self.server = server
        self.connection = self.connect_server()

    def connect_server(self):
        return http.client.HTTPConnection(self.server)

    def request(self, command):
        command_request = command.split()

        if command_request[0] == 'exit':
            return

        self.connection.request(command_request[0], command_request[1])
        #get response from the server
        response = self.connection.getresponse()
        print(response.status, response.reason)

        data_received = response.read()
        print(data_received)

    def close_connection(self):
        self.connection.close()


    def request_times(self, n_times=10, command="GET /index.html"):
        self.connect_server()
        for i in range(n_times):
            self.request(command)
        self.close_connection()

    def request_infinite(self, command="GET /index.html"):
        self.connect_server()
        while 1:
            self.request(command)
        self.close_connection()
