from .app import mcp
from .runtime_diagnostics import run_mcp_server


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
