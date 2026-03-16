import os


def clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")
