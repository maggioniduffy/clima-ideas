import typer

app = typer.Typer(help="clima-nqn command line interface.")


@app.callback()
def main() -> None:
    """clima-nqn command line interface."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo("0.1.0")
