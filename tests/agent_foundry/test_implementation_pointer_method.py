"""Tests for the optional method field on ImplementationPointer."""

from agent_foundry.registry.spec import ImplementationPointer, load_role_spec


class TestImplementationPointerMethod:
    def test_given_pointer_without_method_when_created_then_defaults_to_dunder_call(self):
        pointer = ImplementationPointer(module="some.module", class_name="SomeClass")
        assert pointer.method == "__call__"

    def test_given_pointer_with_explicit_method_when_created_then_stores_method(self):
        pointer = ImplementationPointer(
            module="some.module", class_name="SomeClass", method="review_security"
        )
        assert pointer.method == "review_security"

    def test_given_yaml_spec_without_method_field_when_loaded_then_pointer_method_defaults_to_dunder_call(
        self,
        tmp_path,
    ):
        spec_file = tmp_path / "test_cap.yaml"
        spec_file.write_text(
            """\
name: test_role
description: A test role
version: "1.0.0"
implementation:
  module: some.module
  class_name: SomeClass
inputs_schema:
  type: object
  properties:
    input_field:
      type: string
outputs_schema:
  type: object
  properties:
    output_field:
      type: string
"""
        )
        spec = load_role_spec(spec_file)
        assert spec.implementation.method == "__call__"

    def test_given_yaml_spec_with_method_field_when_loaded_then_pointer_method_is_set(
        self,
        tmp_path,
    ):
        spec_file = tmp_path / "test_cap.yaml"
        spec_file.write_text(
            """\
name: test_role
description: A test role
version: "1.0.0"
implementation:
  module: some.module
  class_name: SomeClass
  method: review_performance
inputs_schema:
  type: object
  properties:
    input_field:
      type: string
outputs_schema:
  type: object
  properties:
    output_field:
      type: string
"""
        )
        spec = load_role_spec(spec_file)
        assert spec.implementation.method == "review_performance"
