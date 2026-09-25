defmodule Vdlarr.RootFolders do
  @moduledoc """
  Root folders media can be saved into. The default root is MEDIA_PATH
  (`Application.get_env(:vdlarr, :media_directory)`) and has no database row - a media
  profile with no `root_folder_id` uses it, exactly as before root folders existed. Extra
  roots (eg: a second mounted share) are `RootFolder` records a profile can pick instead.
  """

  import Ecto.Query, warn: false

  require Logger

  alias Vdlarr.Repo
  alias Vdlarr.Settings
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.RootFolders.RootFolder

  def default_path, do: Application.get_env(:vdlarr, :media_directory)

  def list_root_folders, do: Repo.all(from r in RootFolder, order_by: [asc: fragment("? COLLATE NOCASE", r.name)])

  def get_root_folder!(id), do: Repo.get!(RootFolder, id)

  def change_root_folder(%RootFolder{} = root_folder, attrs \\ %{}), do: RootFolder.changeset(root_folder, attrs)

  @doc """
  Creates a root folder. The directory must already exist and be writable - it's a mount
  point the container should already have, not something to create on a whim.

  Returns {:ok, %RootFolder{}} | {:error, %Ecto.Changeset{}}
  """
  def create_root_folder(attrs) do
    %RootFolder{}
    |> RootFolder.changeset(attrs)
    |> Ecto.Changeset.validate_change(:path, fn :path, path -> validate_usable_directory(path) end)
    |> Repo.insert()
  end

  @doc """
  Deletes a root folder, refusing while any media profile still uses it (their files would
  otherwise silently start landing in the default root).

  Returns {:ok, %RootFolder{}} | {:error, :in_use}
  """
  def delete_root_folder(%RootFolder{} = root_folder) do
    if profile_count(root_folder) > 0, do: {:error, :in_use}, else: Repo.delete(root_folder)
  end

  def profile_count(%RootFolder{id: id}) do
    Repo.aggregate(from(p in MediaProfile, where: p.root_folder_id == ^id), :count)
  end

  @doc """
  The directory a media profile's output path template is relative to.
  """
  def base_path_for(%MediaProfile{root_folder_id: nil}), do: default_path()

  def base_path_for(%MediaProfile{root_folder_id: id}) do
    case Repo.get(RootFolder, id) do
      %RootFolder{path: path} -> path
      nil -> default_path()
    end
  end

  @doc """
  Maps a file path to how Jellyfin sees it: the root containing the file decides the
  replacement prefix (the default root uses the Jellyfin Library Path setting). Paths are
  expanded first, so a template like "../Other/..." resolves to the root it really lands in.
  """
  def jellyfin_path_for(filepath) do
    expanded = Path.expand(filepath)

    candidate_roots()
    |> Enum.filter(fn {root_path, _} -> expanded == root_path or String.starts_with?(expanded, root_path <> "/") end)
    |> Enum.max_by(fn {root_path, _} -> String.length(root_path) end, fn -> nil end)
    |> case do
      {root_path, jellyfin_path} when is_binary(jellyfin_path) and jellyfin_path != "" ->
        jellyfin_path <> String.replace_prefix(expanded, root_path, "")

      _ ->
        filepath
    end
  end

  defp candidate_roots do
    default = {RootFolder.normalize_path(default_path()), Settings.get!(:jellyfin_path_prefix)}
    [default | Enum.map(list_root_folders(), &{&1.path, &1.jellyfin_path})]
  end

  @doc """
  Free bytes on the filesystem holding `path`, via `df` (nil if it can't be read).
  """
  def free_bytes(path) do
    case System.cmd("df", ["-Pk", path], stderr_to_stdout: true) do
      {output, 0} ->
        with [_header, line | _] <- String.split(output, "\n", trim: true),
             [_fs, _size, _used, available | _] <- String.split(line),
             {kb, ""} <- Integer.parse(available) do
          kb * 1024
        else
          _ -> nil
        end

      _ ->
        nil
    end
  end

  @doc """
  One-time conversion for setups that reached a second share by escaping the default root in
  a profile's template ("../Temp-Alternate/Other/{{ title }}.{{ ext }}"). Creates (or reuses)
  a root folder for that directory and makes the template relative to it. Only converts when
  the directory really exists, and is a no-op once nothing starts with "../" - safe to run on
  every boot.
  """
  def convert_relative_profile_templates do
    from(p in MediaProfile, where: is_nil(p.root_folder_id))
    |> Repo.all()
    |> Enum.each(&convert_profile/1)
  end

  defp convert_profile(%MediaProfile{output_path_template: template} = profile) do
    with ["..", dir | rest] when rest != [] and dir != ".." <- template |> String.trim_leading("/") |> Path.split(),
         target = Path.expand(Path.join(default_path(), "../" <> dir)),
         true <- File.dir?(target),
         {:ok, root} <- find_or_create_root(dir, target) do
      new_template = "/" <> Path.join(rest)

      profile
      |> Ecto.Changeset.change(root_folder_id: root.id, output_path_template: new_template)
      |> Repo.update!()

      Logger.info("Moved media profile #{inspect(profile.name)} onto root folder #{inspect(root.name)} (#{target})")
    else
      _ -> :ok
    end
  end

  defp find_or_create_root(name, path) do
    case Repo.get_by(RootFolder, path: path) do
      %RootFolder{} = root -> {:ok, root}
      nil -> %RootFolder{} |> RootFolder.changeset(%{name: unique_name(name), path: path}) |> Repo.insert()
    end
  end

  defp unique_name(name) do
    if Repo.get_by(RootFolder, name: name), do: "#{name} (#{System.unique_integer([:positive])})", else: name
  end

  defp validate_usable_directory(path) do
    probe = Path.join(path, ".vdlarr-write-test-#{System.unique_integer([:positive])}")

    cond do
      not File.dir?(path) ->
        [path: "doesn't exist inside the container - mount it first"]

      File.write(probe, "") != :ok ->
        [path: "isn't writable by the app"]

      true ->
        File.rm(probe)
        []
    end
  end
end
