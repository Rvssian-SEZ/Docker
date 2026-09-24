defmodule VdlarrWeb.Settings.RootFolderController do
  use VdlarrWeb, :controller

  alias Vdlarr.RootFolders

  def create(conn, %{"root_folder" => params}) do
    case RootFolders.create_root_folder(params) do
      {:ok, root_folder} ->
        conn
        |> put_flash(:info, "Root folder \"#{root_folder.name}\" added.")
        |> redirect(to: ~p"/settings#root-folders")

      {:error, changeset} ->
        conn
        |> put_flash(:error, "Couldn't add root folder: #{error_summary(changeset)}")
        |> redirect(to: ~p"/settings#root-folders")
    end
  end

  def delete(conn, %{"id" => id}) do
    root_folder = RootFolders.get_root_folder!(id)

    case RootFolders.delete_root_folder(root_folder) do
      {:ok, _} ->
        conn
        |> put_flash(:info, "Root folder \"#{root_folder.name}\" removed. Files on disk were not touched.")
        |> redirect(to: ~p"/settings#root-folders")

      {:error, :in_use} ->
        conn
        |> put_flash(:error, "\"#{root_folder.name}\" is still used by a media profile - move those profiles first.")
        |> redirect(to: ~p"/settings#root-folders")
    end
  end

  defp error_summary(changeset) do
    changeset
    |> Ecto.Changeset.traverse_errors(fn {msg, opts} ->
      Enum.reduce(opts, msg, fn {key, value}, acc -> String.replace(acc, "%{#{key}}", to_string(value)) end)
    end)
    |> Enum.map_join("; ", fn {field, messages} -> "#{field} #{Enum.join(messages, ", ")}" end)
  end
end
