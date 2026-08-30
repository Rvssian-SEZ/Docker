defmodule Vdlarr.RepoTest do
  use Vdlarr.DataCase
  import Vdlarr.ProfilesFixtures

  alias Vdlarr.Repo
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.JobFixtures.TestJobWorker

  describe "insert_unique_job/1" do
    test "returns {:ok, job} if there is no conflict" do
      job = TestJobWorker.new(%{})

      assert {:ok, %Oban.Job{}} = Vdlarr.Repo.insert_unique_job(job)
    end

    test "returns {:duplicate, original_job} if there is a conflict" do
      job = TestJobWorker.new(%{foo: "bar"}, unique: [period: :infinity])

      {:ok, saved_job_1} = Vdlarr.Repo.insert_unique_job(job)

      assert {:duplicate, saved_job_2} = Vdlarr.Repo.insert_unique_job(job)
      assert saved_job_1.id == saved_job_2.id
    end

    test "returns the error if there is an error" do
      assert {:error, _} = Vdlarr.Repo.insert_unique_job(%Ecto.Changeset{})
    end
  end

  describe "maybe_limit/2" do
    test "applies a limit if provided" do
      media_profile_fixture()
      media_profile_fixture()

      result =
        MediaProfile
        |> Repo.maybe_limit(1)
        |> Repo.aggregate(:count, :id)

      assert result == 1
    end

    test "does not apply a limit if not provided" do
      media_profile_fixture()
      media_profile_fixture()

      result =
        MediaProfile
        |> Repo.maybe_limit(nil)
        |> Repo.aggregate(:count, :id)

      assert result == 2
    end
  end
end
