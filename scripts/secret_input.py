"""Hidden terminal input supporting long bearer tokens. Author: Tishneet."""
import copy
import os
import sys
import termios


def read_hidden_key(prompt="Bedrock API key (hidden): "):
    """Avoid canonical line limits; restore terminal settings even on cancellation."""
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    hidden = copy.deepcopy(previous)
    hidden[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
    hidden[6][termios.VMIN] = 1
    hidden[6][termios.VTIME] = 0
    token = bytearray()
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, hidden)
        print(prompt, end="", file=sys.stderr, flush=True)
        while True:
            character = os.read(fd, 1)
            if not character or character == b"\x04":
                raise EOFError("Key entry cancelled")
            if character in (b"\n", b"\r"):
                return token.decode("ascii").strip()
            if character == b"\x03":
                raise KeyboardInterrupt
            if character in (b"\x7f", b"\x08"):
                if token:
                    token.pop()
            elif character == b"\x15":
                token.clear()
            elif character[0] < 32 or character[0] > 126:
                raise ValueError("Key contains unsupported input characters")
            else:
                token.extend(character)
            if len(token) > 65536:
                raise ValueError("Key exceeds the supported input size")
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, previous)
        print(file=sys.stderr, flush=True)
