defmodule Vdlarr.Boot.PostBootStartupTasksTest do
  use Vdlarr.DataCase

  alias Vdlarr.YtDlp.UpdateWorker
  alias Vdlarr.Boot.PostBootStartupTasks

  describe "update_yt_dlp" do
    test "enqueues an update job" do
      assert [] = all_enqueued(worker: UpdateWorker)

      PostBootStartupTasks.init(%{})

      assert [%Oban.Job{}] = all_enqueued(worker: UpdateWorker)
    end
  end
end
