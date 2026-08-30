defmodule VdlarrWeb.HealthControllerTest do
  use VdlarrWeb.ConnCase

  describe "GET /healthcheck" do
    test "returns ok", %{conn: conn} do
      conn = get(conn, "/healthcheck")
      assert json_response(conn, 200) == %{"status" => "ok"}
    end
  end
end
