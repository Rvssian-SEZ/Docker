defmodule VdlarrWeb.RootFolderControllerTest do
  use VdlarrWeb.ConnCase

  import Vdlarr.ProfilesFixtures

  alias Vdlarr.RootFolders
  alias Vdlarr.RootFolders.RootFolder

  @moduletag :tmp_dir

  test "the Settings page lists the default root and any extra roots", %{conn: conn, tmp_dir: tmp_dir} do
    {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: tmp_dir})

    html = conn |> get(~p"/settings") |> html_response(200)

    assert html =~ "Root Folders"
    assert html =~ Application.get_env(:vdlarr, :media_directory)
    assert html =~ "Archive"
    assert html =~ tmp_dir
  end

  test "adds a root folder", %{conn: conn, tmp_dir: tmp_dir} do
    conn = post(conn, ~p"/root_folders", root_folder: %{name: "Archive", path: tmp_dir})

    assert redirected_to(conn) == "/settings#root-folders"
    assert %RootFolder{path: ^tmp_dir} = Repo.get_by(RootFolder, name: "Archive")
  end

  test "explains why a root folder couldn't be added", %{conn: conn, tmp_dir: tmp_dir} do
    conn = post(conn, ~p"/root_folders", root_folder: %{name: "Missing", path: Path.join(tmp_dir, "missing")})

    assert Phoenix.Flash.get(conn.assigns.flash, :error) =~ "doesn't exist inside the container"
    refute Repo.get_by(RootFolder, name: "Missing")
  end

  test "removes an unused root folder", %{conn: conn, tmp_dir: tmp_dir} do
    {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: tmp_dir})

    delete(conn, ~p"/root_folders/#{root.id}")

    refute Repo.get(RootFolder, root.id)
  end

  test "won't remove a root folder a media profile still uses", %{conn: conn, tmp_dir: tmp_dir} do
    {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: tmp_dir})
    media_profile_fixture(root_folder_id: root.id)

    conn = delete(conn, ~p"/root_folders/#{root.id}")

    assert Phoenix.Flash.get(conn.assigns.flash, :error) =~ "still used by a media profile"
    assert Repo.get(RootFolder, root.id)
  end

  test "the folder picker lists folders under a profile's root", %{conn: conn, tmp_dir: tmp_dir} do
    File.mkdir_p!(Path.join(tmp_dir, "Archived Channel"))
    {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: tmp_dir})
    profile = media_profile_fixture(root_folder_id: root.id)

    assert %{"folders" => ["Archived Channel"]} =
             conn |> get(~p"/sources/folders?media_profile_id=#{profile.id}") |> json_response(200)

    assert %{"folders" => ["Archived Channel"]} =
             conn |> get(~p"/sources/folders?root_folder_id=#{root.id}") |> json_response(200)
  end

  test "the media profile form offers a root folder choice", %{conn: conn, tmp_dir: tmp_dir} do
    {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: tmp_dir})

    html = conn |> get(~p"/media_profiles/new") |> html_response(200)

    assert html =~ "Root folder"
    assert html =~ "Default ("
    assert html =~ "Archive (#{tmp_dir})"
  end
end
