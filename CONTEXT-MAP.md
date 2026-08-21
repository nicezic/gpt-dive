# GPT Dive Context Map

## Contexts

- [Runtime](./docs/runtime/CONTEXT.md) — owns GPT Dive-wide Task, Execution, and asynchronous-work awareness language.
- [Conduit](./docs/conduit/CONTEXT.md) — owns the `@c` conversation/control protocol and Conduit-specific conversation language.

## Relationships

- **Conduit → Runtime**: Conduit consumes the shared Runtime Task/Execution model and TrackedTasks projection; it does not own those concepts.
- **Runtime → Conduit**: Runtime exposes shared asynchronous-work awareness that Conduit may project through its separate tunnel/control surface.
