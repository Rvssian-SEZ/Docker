defmodule Vdlarr.Utils.FunctionUtilsTest do
  use Vdlarr.DataCase

  alias Vdlarr.Utils.FunctionUtils

  describe "wrap_ok/1" do
    test "wraps the provided term in an :ok tuple" do
      assert FunctionUtils.wrap_ok("hello") == {:ok, "hello"}
    end
  end
end
