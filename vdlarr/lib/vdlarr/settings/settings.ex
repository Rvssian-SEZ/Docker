defmodule Vdlarr.Settings do
  @moduledoc """
  The Settings context.
  """
  import Ecto.Query, warn: false

  alias Vdlarr.Repo
  alias Vdlarr.Settings.Setting

  @doc """
  Returns the only setting record. It _should_ be impossible
  to create or delete this record, so it's assertive about
  assuming it's the only one.

  Returns %Setting{}
  """
  def record do
    Setting
    |> limit(1)
    |> Repo.one()
  end

  @doc """
  Updates the setting record.

  Returns {:ok, %Setting{}} | {:error, %Ecto.Changeset{}}
  """
  def update_setting(%Setting{} = setting, attrs) do
    setting
    |> Setting.changeset(attrs)
    |> Repo.update()
    |> tap(fn
      # `Application.get_env(:vdlarr, :timezone)` is read in several hot paths
      # (eg: rendering every row of a table) so it can't be a DB read on every call.
      # Keep it in sync with the persisted setting here, the only place it can change
      # at runtime, so those reads stay fast while the value is still adjustable.
      {:ok, %{timezone: tz}} when is_binary(tz) -> Application.put_env(:vdlarr, :timezone, tz)
      _ -> :ok
    end)
  end

  @doc """
  Updates a setting, returning the new value.
  Is setup to take a keyword list argument so you
  can call it like `Settings.set(restrict_filenames: true)`

  Returns {:ok, value} | {:error, :invalid_key} | {:error, %Ecto.Changeset{}}
  """
  def set([{attr, value}]) do
    record()
    |> update_setting(%{attr => value})
    |> case do
      {:ok, %{^attr => _}} -> {:ok, value}
      {:ok, _} -> {:error, :invalid_key}
      {:error, changeset} -> {:error, changeset}
    end
  end

  @doc """
  Gets the value of a setting.

  Returns {:ok, value} | {:error, :invalid_key}
  """
  def get(name) do
    case Map.fetch(record(), name) do
      {:ok, value} -> {:ok, value}
      :error -> {:error, :invalid_key}
    end
  end

  @doc """
  Gets the value of a setting, raising if it doesn't exist.

  Returns value
  """
  def get!(name) do
    case get(name) do
      {:ok, value} -> value
      {:error, _} -> raise "Setting `#{name}` not found"
    end
  end

  @doc """
  Returns `%Ecto.Changeset{}`
  """
  def change_setting(%Setting{} = setting, attrs \\ %{}) do
    Setting.changeset(setting, attrs)
  end
end
