defmodule VdlarrWeb.Sources.SourceHTMLTest do
  use Vdlarr.DataCase

  import Vdlarr.SourcesFixtures

  alias Vdlarr.Sources
  alias VdlarrWeb.Sources.SourceHTML

  # The helper returns JSON escaped for embedding in a JS string literal
  defp picker_state(attrs) do
    attrs
    |> source_fixture()
    |> Sources.change_source(%{})
    |> SourceHTML.schedule_picker_initial_state()
    |> String.replace(~S(\"), ~S("))
    |> Phoenix.json_library().decode!()
  end

  describe "schedule_picker_initial_state/1" do
    test "a plain interval source opens in interval mode" do
      assert %{"mode" => "interval", "frequency" => 360} = picker_state(%{index_frequency_minutes: 360})
    end

    test "a once-only source opens in once mode" do
      assert %{"mode" => "once"} = picker_state(%{index_frequency_minutes: -1})
    end

    test "a cron source opens in the matching cron mode" do
      assert %{"mode" => "weekly", "weekdays" => [1, 3]} = picker_state(%{index_cron_schedule: "0 3 * * 1,3"})
      assert %{"mode" => "hourly", "every" => 6} = picker_state(%{index_cron_schedule: "30 3,9,15,21 * * *"})
      assert %{"mode" => "custom", "raw" => "0 3 1 * *"} = picker_state(%{index_cron_schedule: "0 3 1 * *"})
    end
  end

  describe "unlisted_interval/1" do
    test "returns an interval that isn't one of the picker's options" do
      assert SourceHTML.unlisted_interval(Sources.change_source(source_fixture(index_frequency_minutes: 45), %{})) == 45
    end

    test "is nil for a listed interval or once-only" do
      assert SourceHTML.unlisted_interval(Sources.change_source(source_fixture(index_frequency_minutes: 1440), %{})) == nil
      assert SourceHTML.unlisted_interval(Sources.change_source(source_fixture(index_frequency_minutes: -1), %{})) == nil
    end
  end
end
