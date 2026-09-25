defmodule VdlarrWeb.Sources.SourceFolderController do
  use VdlarrWeb, :controller

  alias Vdlarr.Repo
  alias Vdlarr.RootFolders
  alias Vdlarr.RootFolders.RootFolder
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.Utils.FilesystemUtils

  @doc """
  Lists existing top-level folders for the source/media profile forms' folder picker - under
  the given media profile's root folder (`media_profile_id`), a specific root folder
  (`root_folder_id`), or the default root.
  """
  def index(conn, params) do
    json(conn, %{folders: FilesystemUtils.list_media_subdirectories(base_path(params))})
  end

  defp base_path(%{"media_profile_id" => id}) when id not in [nil, ""] do
    case Repo.get(MediaProfile, id) do
      %MediaProfile{} = profile -> RootFolders.base_path_for(profile)
      nil -> RootFolders.default_path()
    end
  end

  defp base_path(%{"root_folder_id" => id}) when id not in [nil, ""] do
    case Repo.get(RootFolder, id) do
      %RootFolder{path: path} -> path
      nil -> RootFolders.default_path()
    end
  end

  defp base_path(_params), do: RootFolders.default_path()
end
