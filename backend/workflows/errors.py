"""Workflow errors safe to expose through the HTTP seam. Author: Tishneet."""


class WorkflowError(Exception):
    def __init__(self, code, message, retryable=False, status=400):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.status = retryable, status

    def payload(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
