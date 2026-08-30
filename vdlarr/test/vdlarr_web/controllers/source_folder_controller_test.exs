defmodule VdlarrWeb.SourceFolderControllerTest do
  use VdlarrWeb.ConnCase

  describe "index" do
    setup do
      original_media_directory = Application.get_env(:vdlarr, :media_directory)
      media_directory = Path.join(Application.get_env(:vdlarr, :tmpfile_directory), "source_folders_test")
      File.mkdir_p!(media_directory)
      Application.put_env(:vdlarr, :media_directory, media_directory)

      on_exit(fn ->
        File.rm_rf!(media_directory)
        Application.put_env(:vdlarr, :media_directory, original_media_directory)
      end)

      {:ok, %{media_directory: media_directory}}
    end

    test "returns the list of existing media subdirectories as JSON", %{conn: conn, media_directory: media_directory} do
      File.mkdir_p!(Path.join(media_directory, "Channel A"))
      File.mkdir_p!(Path.join(media_directory, "Channel B"))

      conn = get(conn, ~p"/sources/folders")

      assert json_response(conn, 200) == %{"folders" => ["Channel A", "Channel B"]}
    end

    test "returns an empty list when there are no subdirectories", %{conn: conn} do
      conn = get(conn, ~p"/sources/folders")

      assert json_response(conn, 200) == %{"folders" => []}
    end
  end
end
