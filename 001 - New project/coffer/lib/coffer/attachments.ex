defmodule Coffer.Attachments do
  @moduledoc """
  Shared helpers for validating and storing uploaded files (spec §10:
  contracts want PDFs primarily plus common doc formats; ledger receipts —
  a later phase — want PDF/image). Each resource (contracts now, ledger
  receipts later) keeps its own dedicated `*_attachments` table (spec §4.8
  leaves polymorphic-vs-dedicated as our call; dedicated tables avoid the
  FK-integrity tradeoff the spec itself flags) but shares this validation
  and storage logic so the rules don't drift between them.
  """

  @max_bytes 25_000_000

  @allowed_content_types %{
    "application/pdf" => ".pdf",
    "application/msword" => ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document" => ".docx",
    "application/vnd.ms-excel" => ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" => ".xlsx",
    "image/png" => ".png",
    "image/jpeg" => ".jpg"
  }

  def max_bytes, do: @max_bytes
  def allowed_content_types, do: Map.keys(@allowed_content_types)

  def allowed?(content_type), do: Map.has_key?(@allowed_content_types, content_type)

  @doc "Base directory for uploaded files, e.g. `/app/storage` in prod."
  def storage_path, do: Application.fetch_env!(:coffer, :storage_path)

  @doc """
  Copies a completed LiveView upload entry into storage under `subdir`
  (e.g. `"contracts"`), returning the RELATIVE path to store in the DB —
  never an absolute host path (spec §10, host path may change between
  test/prod), and a sanitized original filename.
  """
  def store_upload!(subdir, %Plug.Upload{} = upload, original_filename) do
    safe_name = sanitize_filename(original_filename)
    relative_path = Path.join([subdir, Ecto.UUID.generate() <> "_" <> safe_name])
    dest = Path.join(storage_path(), relative_path)

    dest |> Path.dirname() |> File.mkdir_p!()
    File.cp!(upload.path, dest)

    relative_path
  end

  defp sanitize_filename(name) do
    name
    |> Path.basename()
    |> String.replace(~r/[^a-zA-Z0-9._-]/, "_")
  end
end
