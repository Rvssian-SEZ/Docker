defmodule Vdlarr.RootFoldersTest do
  use Vdlarr.DataCase

  import Vdlarr.ProfilesFixtures

  alias Vdlarr.Settings
  alias Vdlarr.RootFolders
  alias Vdlarr.RootFolders.RootFolder
  alias Vdlarr.Profiles.MediaProfile

  @moduletag :tmp_dir

  setup %{tmp_dir: tmp_dir} do
    Settings.set(jellyfin_path_prefix: nil)
    archive = Path.join(tmp_dir, "archive")
    File.mkdir_p!(archive)

    {:ok, archive: archive}
  end

  describe "create_root_folder/1" do
    test "creates a root for an existing, writable directory and normalises the path", %{archive: archive} do
      assert {:ok, %RootFolder{} = root} = RootFolders.create_root_folder(%{name: " Archive ", path: archive <> "/"})

      assert root.name == "Archive"
      assert root.path == archive
    end

    test "rejects a relative path", _ do
      assert {:error, changeset} = RootFolders.create_root_folder(%{name: "Rel", path: "downloads/archive"})
      assert "must be an absolute path, eg: /downloads/archive" in errors_on(changeset).path
    end

    test "rejects a directory that doesn't exist", %{tmp_dir: tmp_dir} do
      assert {:error, changeset} = RootFolders.create_root_folder(%{name: "Nope", path: Path.join(tmp_dir, "missing")})
      assert "doesn't exist inside the container - mount it first" in errors_on(changeset).path
    end

    test "rejects duplicate names and paths", %{archive: archive} do
      {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: archive})

      assert {:error, changeset} = RootFolders.create_root_folder(%{name: "Archive", path: archive})
      assert errors_on(changeset)[:name] || errors_on(changeset)[:path]
    end
  end

  describe "delete_root_folder/1" do
    test "refuses while a media profile uses it", %{archive: archive} do
      {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: archive})
      media_profile_fixture(root_folder_id: root.id)

      assert {:error, :in_use} = RootFolders.delete_root_folder(root)
      assert Repo.get(RootFolder, root.id)
    end

    test "deletes an unused root", %{archive: archive} do
      {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: archive})

      assert {:ok, _} = RootFolders.delete_root_folder(root)
      refute Repo.get(RootFolder, root.id)
    end
  end

  describe "base_path_for/1" do
    test "uses MEDIA_PATH when the profile has no root folder" do
      assert RootFolders.base_path_for(%MediaProfile{root_folder_id: nil}) == Application.get_env(:vdlarr, :media_directory)
    end

    test "uses the profile's root folder", %{archive: archive} do
      {:ok, root} = RootFolders.create_root_folder(%{name: "Archive", path: archive})

      assert RootFolders.base_path_for(%MediaProfile{root_folder_id: root.id}) == archive
    end

    test "falls back to MEDIA_PATH if the root folder no longer exists" do
      assert RootFolders.base_path_for(%MediaProfile{root_folder_id: -1}) == Application.get_env(:vdlarr, :media_directory)
    end
  end

  describe "jellyfin_path_for/1" do
    test "leaves paths alone when nothing is configured", %{archive: archive} do
      {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: archive})

      assert RootFolders.jellyfin_path_for(Path.join(archive, "a.mp4")) == Path.join(archive, "a.mp4")
    end

    test "maps the default root using the Jellyfin Library Path setting" do
      Settings.set(jellyfin_path_prefix: "/data/youtube")
      media_directory = Application.get_env(:vdlarr, :media_directory)

      assert RootFolders.jellyfin_path_for(Path.join(media_directory, "show/a.mp4")) == "/data/youtube/show/a.mp4"
    end

    test "maps an extra root using its own Jellyfin path", %{archive: archive} do
      Settings.set(jellyfin_path_prefix: "/data/youtube")
      {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: archive, jellyfin_path: "/data/archive"})

      assert RootFolders.jellyfin_path_for(Path.join(archive, "show/a.mp4")) == "/data/archive/show/a.mp4"
    end

    test "resolves '..' before matching, so escaped templates map to the root they land in", %{archive: archive} do
      {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: archive, jellyfin_path: "/data/archive"})
      escaped = Path.join([archive, "..", "archive", "a.mp4"])

      assert RootFolders.jellyfin_path_for(escaped) == "/data/archive/a.mp4"
    end

    test "the most specific root wins when roots are nested", %{archive: archive} do
      nested = Path.join(archive, "nested")
      File.mkdir_p!(nested)
      {:ok, _} = RootFolders.create_root_folder(%{name: "Archive", path: archive, jellyfin_path: "/data/archive"})
      {:ok, _} = RootFolders.create_root_folder(%{name: "Nested", path: nested, jellyfin_path: "/data/nested"})

      assert RootFolders.jellyfin_path_for(Path.join(nested, "a.mp4")) == "/data/nested/a.mp4"
    end
  end

  describe "convert_relative_profile_templates/0" do
    setup %{tmp_dir: tmp_dir} do
      original = Application.get_env(:vdlarr, :media_directory)
      media = Path.join(tmp_dir, "youtube")
      alternate = Path.join(tmp_dir, "Temp-Alternate")
      File.mkdir_p!(media)
      File.mkdir_p!(alternate)
      Application.put_env(:vdlarr, :media_directory, media)
      on_exit(fn -> Application.put_env(:vdlarr, :media_directory, original) end)

      {:ok, alternate: alternate}
    end

    test "moves a '../Dir/...' template onto a root folder for that directory", %{alternate: alternate} do
      profile = media_profile_fixture(output_path_template: "../Temp-Alternate/Other/{{ source_custom_name }}/{{ title }}.{{ ext }}")

      RootFolders.convert_relative_profile_templates()
      profile = Repo.reload(profile) |> Repo.preload(:root_folder)

      assert profile.root_folder.name == "Temp-Alternate"
      assert profile.root_folder.path == alternate
      assert profile.output_path_template == "/Other/{{ source_custom_name }}/{{ title }}.{{ ext }}"
    end

    test "reuses one root for several profiles and is a no-op on later runs" do
      a = media_profile_fixture(output_path_template: "../Temp-Alternate/A/{{ title }}.{{ ext }}")
      b = media_profile_fixture(output_path_template: "/../Temp-Alternate/B/{{ title }}.{{ ext }}")

      RootFolders.convert_relative_profile_templates()
      RootFolders.convert_relative_profile_templates()

      assert Repo.aggregate(RootFolder, :count) == 1
      assert Repo.reload(a).root_folder_id == Repo.reload(b).root_folder_id
      assert Repo.reload(b).output_path_template == "/B/{{ title }}.{{ ext }}"
    end

    test "leaves templates alone when the directory doesn't exist, or escapes further than one level" do
      missing = media_profile_fixture(output_path_template: "../Nowhere/{{ title }}.{{ ext }}")
      deep = media_profile_fixture(output_path_template: "../../etc/{{ title }}.{{ ext }}")
      normal = media_profile_fixture(output_path_template: "/{{ title }}.{{ ext }}")

      RootFolders.convert_relative_profile_templates()

      for profile <- [missing, deep, normal] do
        assert Repo.reload(profile).output_path_template == profile.output_path_template
        assert Repo.reload(profile).root_folder_id == nil
      end
    end
  end

  describe "free_bytes/1" do
    test "reports free space for an existing directory", %{archive: archive} do
      assert is_integer(RootFolders.free_bytes(archive))
    end

    test "is nil for a path that can't be read", %{tmp_dir: tmp_dir} do
      assert RootFolders.free_bytes(Path.join(tmp_dir, "missing")) == nil
    end
  end
end
