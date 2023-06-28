
class NetworkError(ConnectionError):
    """
    Exception raised when there is a network connection error
    """

class BrowserException(Exception):
    """
    Exception raised when there is an error within the browser
    """

class BrowserNotInstalled(BrowserException):
    """
    Exception raised when the browser selected is not installed on the machine
    """

class BrowserNotSupported(BrowserException):
    """
    Exception raised when the browser selected is not supported by selenium
    """
