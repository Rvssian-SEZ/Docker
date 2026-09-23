defmodule VdlarrWeb.SourceScheduleControllerTest do
  use VdlarrWeb.ConnCase

  import Vdlarr.SourcesFixtures

  defp preview(conn, params), do: conn |> get(~p"/sources/schedule_preview", params) |> json_response(200)

  describe "preview" do
    test "describes a cron schedule with its next five runs", %{conn: conn} do
      assert %{"ok" => true, "summary" => "Runs daily at 03:00", "next_runs" => runs} =
               preview(conn, %{"cron" => "0 3 * * *", "frequency" => "1440"})

      assert length(runs) == 5
      assert Enum.all?(runs, &(&1 =~ "03:00"))
    end

    test "reports an invalid cron expression", %{conn: conn} do
      assert %{"ok" => false, "error" => "Invalid cron expression" <> _} = preview(conn, %{"cron" => "nope"})
    end

    test "describes a once-only source", %{conn: conn} do
      assert %{"ok" => true, "summary" => "Indexed once" <> _, "next_runs" => []} =
               preview(conn, %{"cron" => "", "frequency" => "-1"})
    end

    test "a new source's interval starts right after saving", %{conn: conn} do
      assert %{"ok" => true, "summary" => "Every 6 hours" <> _, "next_runs" => ["Right after saving" | rest]} =
               preview(conn, %{"cron" => "", "frequency" => "360"})

      assert length(rest) == 4
    end

    test "an existing source's interval counts from its last index", %{conn: conn} do
      source = source_fixture(index_frequency_minutes: 60, last_indexed_at: DateTime.add(DateTime.utc_now(), -30 * 60))

      assert %{"summary" => "Every hour" <> _, "next_runs" => [first | _]} =
               preview(conn, %{"cron" => "", "frequency" => "60", "source_id" => to_string(source.id)})

      refute first in ["Due now", "Right after saving"]
    end

    test "an overdue interval is due now", %{conn: conn} do
      source = source_fixture(index_frequency_minutes: 60, last_indexed_at: DateTime.add(DateTime.utc_now(), -3 * 3600))

      assert %{"next_runs" => ["Due now" | _]} =
               preview(conn, %{"cron" => "", "frequency" => "60", "source_id" => to_string(source.id)})
    end

    test "answers a browser fetch's default Accept header", %{conn: conn} do
      conn = conn |> put_req_header("accept", "*/*") |> get(~p"/sources/schedule_preview", %{"cron" => "0 3 * * *"})

      assert %{"ok" => true} = json_response(conn, 200)
    end

    test "asks for an interval when there's neither a cron nor a frequency", %{conn: conn} do
      assert %{"ok" => false, "error" => "Pick how often to index"} = preview(conn, %{"cron" => ""})
    end
  end
end
