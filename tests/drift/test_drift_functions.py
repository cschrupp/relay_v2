import ast

from conftest import long_function

from relay.drift.functions import OversizedFunction, oversized_functions


def test_budget_is_inclusive() -> None:
    tree = ast.parse(long_function("fits", 80) + long_function("over", 81))

    assert oversized_functions(tree, "m.py", 80) == [OversizedFunction("m.py", 81, "over", 81)]


def test_methods_nested_and_async_functions_are_named_and_counted() -> None:
    inner = "\n".join("    " + line for line in long_function("inner", 85).splitlines())
    source = (
        "class Service:\n"
        + "\n".join("    " + line for line in long_function("run", 90).splitlines())
        + "\n\n"
        + "def outer():\n"
        + inner
        + "\n    return inner\n\n"
        + "async "
        + long_function("fetch", 82)
    )

    found = oversized_functions(ast.parse(source), "m.py", 80)

    assert {(item.name, item.lines) for item in found} == {
        ("Service.run", 90),
        ("outer", 87),
        ("outer.inner", 85),
        ("fetch", 82),
    }
