import os
import sys


def check_for_file(root, file_name):
    """
        Checks if a project file exists
    """

    return os.path.exists(os.path.join(root, file_name))


def wrap_exception(exceptionName, message):
    trace = sys.exc_info()[2]
    raise exceptionName(message, None, trace)


def popall(deque):
    #Preallocate the list to save memory resizing.
    r = len(deque) * [None]
    for i in range(len(r)):
        r[i] = deque.popleft()
    return r
