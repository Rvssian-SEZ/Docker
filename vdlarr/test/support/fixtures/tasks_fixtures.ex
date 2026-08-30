defmodule Vdlarr.TasksFixtures do
  @moduledoc """
  This module defines test helpers for creating
  entities via the `Vdlarr.Tasks` context.
  """

  alias Vdlarr.JobFixtures
  alias Vdlarr.SourcesFixtures

  @doc """
  Generate a task.
  """
  def task_fixture(attrs \\ %{}) do
    {:ok, task} =
      attrs
      |> Enum.into(%{
        source_id: SourcesFixtures.source_fixture().id,
        job_id: JobFixtures.job_fixture().id
      })
      |> Vdlarr.Tasks.create_task()

    task
  end
end
