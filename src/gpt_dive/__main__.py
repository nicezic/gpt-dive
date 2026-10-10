from .app import mcp
from .runtime_diagnostics import configure_runtime_logging, run_mcp_server


def main() -> None:
    configure_runtime_logging()
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
