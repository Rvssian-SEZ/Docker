defmodule VdlarrWeb.SourceControllerTest do
  use VdlarrWeb.ConnCase

  import Ecto.Query, warn: false
  import Vdlarr.MediaFixtures
  import Vdlarr.SourcesFixtures
  import Vdlarr.ProfilesFixtures

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Media.FileSyncingWorker
  alias Vdlarr.Sources.SourceDeletionWorker
  alias Vdlarr.Downloading.MediaDownloadWorker
  alias Vdlarr.Metadata.SourceMetadataStorageWorker
  alias Vdlarr.SlowIndexing.MediaCollectionIndexingWorker

  setup do
    media_profile = media_profile_fixture()

    {
      :ok,
      %{
        create_attrs: %{
          media_profile_id: media_profile.id,
          collection_type: "channel",
          original_url: "https://www.youtube.com/source/abc123"
        },
        update_attrs: %{
          original_url: "https://www.youtube.com/source/321xyz"
        },
        invalid_attrs: %{original_url: nil, media_profile_id: nil}
      }
    }
  end

  describe "index" do
    # Most of the tests are in `index_grid_live_test.exs`
    test "returns 200", %{conn: conn} do
      conn = get(conn, ~p"/sources")
      assert html_response(conn, 200) =~ "Dashboard"
    end

    test "is also served at the app root, since Dashboard is the default landing page", %{conn: conn} do
      conn = get(conn, ~p"/")
      assert html_response(conn, 200) =~ "Dashboard"
    end
  end

  describe "hidden_index" do
    # Hidden-vs-visible filtering behaviour is covered in `index_grid_live_test.exs`
    test "returns 200", %{conn: conn} do
      conn = get(conn, ~p"/sources/hidden")
      assert html_response(conn, 200) =~ "Hidden Sources"
    end
  end

  describe "poster" do
    test "returns 404 when the source has no poster anywhere", %{conn: conn} do
      source = source_fixture()

      conn = get(conn, ~p"/sources/#{source.id}/poster")

      assert conn.status == 404
    end

    test "serves the source's own poster_filepath when present", %{conn: conn} do
      source = source_fixture(poster_filepath: thumbnail_filepath_fixture())

      conn = get(conn, ~p"/sources/#{source.id}/poster")

      assert conn.status == 200
    end

    test "falls back to the metadata poster when the source has no library poster", %{conn: conn} do
      source = source_with_metadata_attachments()

      conn = get(conn, ~p"/sources/#{source.id}/poster")

      assert conn.status == 200
    end

    test "falls back to the metadata fanart when there's no poster at all", %{conn: conn} do
      source = source_with_metadata_attachments()

      source
      |> Repo.preload(:metadata)
      |> Map.fetch!(:metadata)
      |> Ecto.Changeset.change(poster_filepath: nil)
      |> Repo.update!()

      conn = get(conn, ~p"/sources/#{source.id}/poster")

      assert conn.status == 200
    end

    test "returns 404 when the DB points at a file that no longer exists on disk", %{conn: conn} do
      source = source_fixture(poster_filepath: "/tmp/does-not-exist-#{:rand.uniform(1_000_000)}.jpg")

      conn = get(conn, ~p"/sources/#{source.id}/poster")

      assert conn.status == 404
    end
  end

  describe "upload_poster" do
    test "accepts a valid image and sets custom_poster_filepath", %{conn: conn} do
      source = source_fixture()
      upload = %Plug.Upload{path: thumbnail_filepath_fixture(), filename: "poster.jpg", content_type: "image/jpeg"}

      conn = post(conn, ~p"/sources/#{source.id}/poster", %{"poster" => upload})

      assert redirected_to(conn) == ~p"/sources/#{source.id}/edit"
      updated_source = Repo.get!(Source, source.id)
      assert updated_source.custom_poster_filepath
      assert File.exists?(updated_source.custom_poster_filepath)
    end

    test "a custom poster takes priority over an existing metadata poster once uploaded", %{conn: conn} do
      source = source_with_metadata_attachments()
      upload = %Plug.Upload{path: thumbnail_filepath_fixture(), filename: "poster.jpg", content_type: "image/jpeg"}

      post(conn, ~p"/sources/#{source.id}/poster", %{"poster" => upload})

      conn = get(build_conn(), ~p"/sources/#{source.id}/poster")
      updated_source = Repo.get!(Source, source.id)
      assert conn.status == 200
      assert conn.resp_body == File.read!(updated_source.custom_poster_filepath)
    end

    test "rejects a non-image content type", %{conn: conn} do
      source = source_fixture()
      upload = %Plug.Upload{path: thumbnail_filepath_fixture(), filename: "poster.txt", content_type: "text/plain"}

      conn = post(conn, ~p"/sources/#{source.id}/poster", %{"poster" => upload})

      assert redirected_to(conn) == ~p"/sources/#{source.id}/edit"
      refute Repo.get!(Source, source.id).custom_poster_filepath
    end
  end

  describe "remove_custom_poster" do
    test "clears the field and deletes the file", %{conn: conn} do
      custom_poster_path = copy_of_thumbnail_fixture()
      source = source_fixture(custom_poster_filepath: custom_poster_path)

      conn = delete(conn, ~p"/sources/#{source.id}/poster")

      assert redirected_to(conn) == ~p"/sources/#{source.id}/edit"
      refute Repo.get!(Source, source.id).custom_poster_filepath
      refute File.exists?(custom_poster_path)
    end

    test "falls back to the metadata poster after removal", %{conn: conn} do
      source = source_with_metadata_attachments(%{custom_poster_filepath: copy_of_thumbnail_fixture()})

      delete(conn, ~p"/sources/#{source.id}/poster")

      conn = get(build_conn(), ~p"/sources/#{source.id}/poster")
      assert conn.status == 200
      assert conn.resp_body == File.read!(source.metadata.poster_filepath)
    end

    test "does nothing when there's no custom poster to remove", %{conn: conn} do
      source = source_fixture()

      conn = delete(conn, ~p"/sources/#{source.id}/poster")

      assert redirected_to(conn) == ~p"/sources/#{source.id}/edit"
    end
  end

  defp copy_of_thumbnail_fixture do
    destination = Path.join(System.tmp_dir!(), "poster_test_#{:rand.uniform(1_000_000)}.jpg")
    File.cp!(thumbnail_filepath_fixture(), destination)
    destination
  end

  describe "new source" do
    test "renders form", %{conn: conn} do
      conn = get(conn, ~p"/sources/new")
      assert html_response(conn, 200) =~ "New Source"
    end

    test "preloads some attributes when using a template", %{conn: conn} do
      source = source_fixture(custom_name: "My first source", download_cutoff_date: "2021-01-01")

      conn = get(conn, ~p"/sources/new", %{"template_id" => source.id})
      assert html_response(conn, 200) =~ "New Source"
      assert html_response(conn, 200) =~ "2021-01-01"
      refute html_response(conn, 200) =~ source.custom_name
    end
  end

  describe "create source" do
    test "redirects to show when data is valid", %{conn: conn, create_attrs: create_attrs} do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)
      conn = post(conn, ~p"/sources", source: create_attrs)

      assert %{id: id} = redirected_params(conn)
      assert redirected_to(conn) == ~p"/sources/#{id}"

      conn = get(conn, ~p"/sources/#{id}")
      assert html_response(conn, 200) =~ "Source"
    end

    test "renders errors when data is invalid", %{conn: conn, invalid_attrs: invalid_attrs} do
      conn = post(conn, ~p"/sources", source: invalid_attrs)
      assert html_response(conn, 200) =~ "New Source"
    end

    test "cannot set internal-only filepath fields via params (arbitrary file read/delete guard)", %{
      conn: conn,
      create_attrs: create_attrs
    } do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)

      malicious_attrs =
        Map.merge(create_attrs, %{
          poster_filepath: "/etc/passwd",
          custom_poster_filepath: "/etc/passwd",
          nfo_filepath: "/etc/passwd"
        })

      conn = post(conn, ~p"/sources", source: malicious_attrs)

      assert %{id: id} = redirected_params(conn)
      source = Repo.get!(Source, id)
      refute source.poster_filepath
      refute source.custom_poster_filepath
      refute source.nfo_filepath
    end

    test "delay_automatic_download puts a playlist source into manual selection mode", %{
      conn: conn,
      create_attrs: create_attrs
    } do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)

      playlist_attrs =
        Map.merge(create_attrs, %{collection_type: "playlist", delay_automatic_download: "true"})

      conn = post(conn, ~p"/sources", source: playlist_attrs)

      assert %{id: id} = redirected_params(conn)
      source = Repo.get!(Source, id)

      assert source.selection_mode == :manual
      refute source.download_media
    end

    test "without delay_automatic_download, a playlist source downloads normally", %{
      conn: conn,
      create_attrs: create_attrs
    } do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)

      playlist_attrs = Map.merge(create_attrs, %{collection_type: "playlist"})

      conn = post(conn, ~p"/sources", source: playlist_attrs)

      assert %{id: id} = redirected_params(conn)
      source = Repo.get!(Source, id)

      assert source.selection_mode == :all
    end
  end

  describe "edit source" do
    setup [:create_source]

    test "renders form for editing chosen source", %{conn: conn, source: source} do
      conn = get(conn, ~p"/sources/#{source}/edit")
      assert html_response(conn, 200) =~ "Editing \"#{source.custom_name}\""
    end
  end

  describe "update source" do
    setup [:create_source]

    test "redirects when data is valid", %{conn: conn, source: source, update_attrs: update_attrs} do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)

      conn = put(conn, ~p"/sources/#{source}", source: update_attrs)
      assert redirected_to(conn) == ~p"/sources/#{source}"

      conn = get(conn, ~p"/sources/#{source}")
      assert html_response(conn, 200) =~ "https://www.youtube.com/source/321xyz"
    end

    test "renders errors when data is invalid", %{
      conn: conn,
      source: source,
      invalid_attrs: invalid_attrs
    } do
      conn = put(conn, ~p"/sources/#{source}", source: invalid_attrs)
      assert html_response(conn, 200) =~ "Editing \"#{source.custom_name}\""
    end

    test "cannot set internal-only filepath fields via params (arbitrary file read/delete guard)", %{
      conn: conn,
      source: source,
      update_attrs: update_attrs
    } do
      expect(YtDlpRunnerMock, :run, 1, &runner_function_mock/5)

      malicious_attrs =
        Map.merge(update_attrs, %{
          poster_filepath: "/etc/passwd",
          custom_poster_filepath: "/etc/passwd",
          fanart_filepath: "/etc/passwd",
          banner_filepath: "/etc/passwd",
          nfo_filepath: "/etc/passwd",
          series_directory: "/etc"
        })

      put(conn, ~p"/sources/#{source}", source: malicious_attrs)

      updated_source = Repo.get!(Source, source.id)
      refute updated_source.poster_filepath
      refute updated_source.custom_poster_filepath
      refute updated_source.fanart_filepath
      refute updated_source.banner_filepath
      refute updated_source.nfo_filepath
      refute updated_source.series_directory
    end
  end

  describe "delete source in all cases" do
    setup [:create_source]

    test "redirects to the sources page", %{conn: conn, source: source} do
      conn = delete(conn, ~p"/sources/#{source}")
      assert redirected_to(conn) == ~p"/sources"
    end

    test "sets marked_for_deletion_at", %{conn: conn, source: source} do
      delete(conn, ~p"/sources/#{source}")
      assert Repo.reload!(source).marked_for_deletion_at
    end
  end

  describe "delete source when just deleting the records" do
    setup [:create_source]

    test "enqueues a job without the delete_files arg", %{conn: conn, source: source} do
      delete(conn, ~p"/sources/#{source}")

      assert [%{args: %{"delete_files" => false}}] = all_enqueued(worker: SourceDeletionWorker)
    end
  end

  describe "delete source when deleting the records and files" do
    setup [:create_source]

    test "enqueues a job without the delete_files arg", %{conn: conn, source: source} do
      delete(conn, ~p"/sources/#{source}?delete_files=true")

      assert [%{args: %{"delete_files" => true}}] = all_enqueued(worker: SourceDeletionWorker)
    end
  end

  describe "force_download_pending" do
    test "enqueues pending download tasks", %{conn: conn} do
      source = source_fixture()
      _media_item = media_item_fixture(%{source_id: source.id, media_filepath: nil})

      assert [] = all_enqueued(worker: MediaDownloadWorker)
      post(conn, ~p"/sources/#{source.id}/force_download_pending")
      assert [_] = all_enqueued(worker: MediaDownloadWorker)
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/force_download_pending")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  describe "force_download_failed" do
    test "enqueues failed download tasks", %{conn: conn} do
      source = source_fixture()
      _media_item = media_item_fixture(%{source_id: source.id, media_filepath: nil, last_error: "Some error"})

      assert [] = all_enqueued(worker: MediaDownloadWorker)
      post(conn, ~p"/sources/#{source.id}/force_download_failed")
      assert [_] = all_enqueued(worker: MediaDownloadWorker)
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/force_download_failed")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  describe "restore_automatic_downloads" do
    test "restores selection_mode and clears prevent_download, redirects to the source page", %{conn: conn} do
      source = source_fixture(%{collection_type: :playlist, selection_mode: :manual, download_media: false})
      media_item = media_item_fixture(%{source_id: source.id, prevent_download: true})

      conn = post(conn, ~p"/sources/#{source.id}/restore_automatic_downloads")

      assert redirected_to(conn) == ~p"/sources/#{source.id}"
      assert Repo.reload(source).selection_mode == :all
      assert Repo.reload(source).download_media
      refute Repo.reload(media_item).prevent_download
    end
  end

  describe "start_all" do
    test "enables the source and turns downloading on when something is pending", %{conn: conn} do
      source = source_fixture(%{enabled: false, download_media: false})
      _media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      conn = post(conn, ~p"/sources/#{source.id}/start_all")

      assert redirected_to(conn) == ~p"/sources/#{source.id}"
      source = Repo.reload(source)
      assert source.enabled
      assert source.download_media
    end

    test "does not enable the source when nothing is pending", %{conn: conn} do
      source = source_fixture(%{enabled: false, download_media: false})

      post(conn, ~p"/sources/#{source.id}/start_all")

      source = Repo.reload(source)
      refute source.enabled
      refute source.download_media
    end
  end

  describe "pause_all" do
    test "turns off download_media and cancels an in-progress download, leaving the source enabled", %{conn: conn} do
      source = source_fixture(%{enabled: true, download_media: true})
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)
      {:ok, task} = MediaDownloadWorker.kickoff_with_task(media_item)
      set_job_state(task, :executing)

      conn = post(conn, ~p"/sources/#{source.id}/pause_all")

      assert redirected_to(conn) == ~p"/sources/#{source.id}"
      source = Repo.reload(source)
      assert source.enabled
      refute source.download_media
      refute Repo.get(Vdlarr.Tasks.Task, task.id)
    end

    test "does nothing when there are no active or queued downloads", %{conn: conn} do
      source = source_fixture(%{enabled: true, download_media: true})

      post(conn, ~p"/sources/#{source.id}/pause_all")

      assert Repo.reload(source).download_media
    end
  end

  describe "stop_all" do
    test "disables the source and cancels a queued download", %{conn: conn} do
      source = source_fixture(%{enabled: true, download_media: true})
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)
      {:ok, _task} = MediaDownloadWorker.kickoff_with_task(media_item)

      conn = post(conn, ~p"/sources/#{source.id}/stop_all")

      assert redirected_to(conn) == ~p"/sources/#{source.id}"
      source = Repo.reload(source)
      refute source.enabled
      refute source.download_media
      refute_enqueued(worker: MediaDownloadWorker)
    end

    test "does nothing when there are no active or queued downloads", %{conn: conn} do
      source = source_fixture(%{enabled: true, download_media: true})

      post(conn, ~p"/sources/#{source.id}/stop_all")

      assert Repo.reload(source).enabled
    end
  end

  describe "force_redownload" do
    test "enqueues re-download tasks", %{conn: conn} do
      source = source_fixture()
      _media_item = media_item_fixture(source_id: source.id, media_downloaded_at: now())

      assert [] = all_enqueued(worker: MediaDownloadWorker)
      post(conn, ~p"/sources/#{source.id}/force_redownload")
      assert [_] = all_enqueued(worker: MediaDownloadWorker)
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/force_redownload")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  describe "force_index" do
    test "forces an index", %{conn: conn} do
      source = source_fixture()

      assert [] = all_enqueued(worker: MediaCollectionIndexingWorker)
      post(conn, ~p"/sources/#{source.id}/force_index")
      assert [_] = all_enqueued(worker: MediaCollectionIndexingWorker)
    end

    test "forces an index even if one wouldn't normally run", %{conn: conn} do
      source = source_fixture(index_frequency_minutes: 0, last_indexed_at: DateTime.utc_now())

      post(conn, ~p"/sources/#{source.id}/force_index")
      assert [job] = all_enqueued(worker: MediaCollectionIndexingWorker)
      assert job.args == %{"id" => source.id, "force" => true}
    end

    test "deletes pending indexing tasks", %{conn: conn} do
      source = source_fixture()
      {:ok, task} = MediaCollectionIndexingWorker.kickoff_with_task(source)
      job = Repo.preload(task, :job).job

      assert job.state == "available"
      post(conn, ~p"/sources/#{source.id}/force_index")
      assert Repo.reload!(job).state == "cancelled"
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/force_index")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  describe "force_metadata_refresh" do
    test "forces a metadata refresh", %{conn: conn} do
      source = source_fixture()

      assert [] = all_enqueued(worker: SourceMetadataStorageWorker)
      post(conn, ~p"/sources/#{source.id}/force_metadata_refresh")
      assert [_] = all_enqueued(worker: SourceMetadataStorageWorker)
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/force_metadata_refresh")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  describe "sync_files_on_disk" do
    test "forces a file sync", %{conn: conn} do
      source = source_fixture()

      assert [] = all_enqueued(worker: FileSyncingWorker)
      post(conn, ~p"/sources/#{source.id}/sync_files_on_disk")
      assert [_] = all_enqueued(worker: FileSyncingWorker)
    end

    test "redirects to the source page", %{conn: conn} do
      source = source_fixture()

      conn = post(conn, ~p"/sources/#{source.id}/sync_files_on_disk")
      assert redirected_to(conn) == ~p"/sources/#{source.id}"
    end
  end

  defp create_source(_) do
    source = source_fixture()
    media_item = media_item_with_attachments(%{source_id: source.id})

    %{source: source, media_item: media_item}
  end

  defp set_job_state(task, job_state) do
    Oban.Job
    |> where([j], j.id == ^task.job_id)
    |> Repo.update_all(set: [state: to_string(job_state)])
  end

  defp runner_function_mock(_url, :get_source_details, _opts, _ot, _addl) do
    {
      :ok,
      Phoenix.json_library().encode!(%{
        channel: "some channel name",
        channel_id: "some_channel_id_#{:rand.uniform(1_000_000)}",
        playlist_id: "some_playlist_id_#{:rand.uniform(1_000_000)}",
        playlist_title: "some playlist name"
      })
    }
  end
end
