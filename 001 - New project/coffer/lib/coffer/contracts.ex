defmodule Coffer.Contracts do
  @moduledoc """
  Vendors' contracts/subscriptions (spec §4.6). No approval workflow, same
  as the ledger — any Staff/Admin creates/edits directly, every write
  audit-logged.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Accounts.User
  alias Coffer.Contracts.{Contract, Attachment}
  alias Coffer.Attachments

  @preloads [:vendor, :currency, :budget_envelope, :created_by, :attachments]

  def list_contracts do
    Contract
    |> order_by(asc: :renewal_date, asc: :name)
    |> preload(^@preloads)
    |> Repo.all()
  end

  @doc "Active contracts with a `renewal_date` set — the renewal worker's own working set."
  def list_active_with_renewal_date do
    Contract
    |> where(status: :active)
    |> where([c], not is_nil(c.renewal_date))
    |> Repo.all()
  end

  def get_contract!(id), do: Repo.get!(Contract, id) |> Repo.preload(@preloads)

  def change_contract(%Contract{} = contract, attrs \\ %{}),
    do: Contract.changeset(contract, attrs)

  def create_contract(attrs, %User{} = actor) do
    changeset =
      %Contract{}
      |> Contract.changeset(attrs)
      |> Ecto.Changeset.put_change(:created_by_id, actor.id)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:contract, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{contract: c} ->
      AuditLog.record(actor.id, :create, "Contract", c.id, %{after: serialize(c)})
    end)
    |> Repo.transaction()
    |> unwrap(:contract)
  end

  def update_contract(%Contract{} = contract, attrs, %User{} = actor) do
    before = serialize(contract)
    changeset = Contract.changeset(contract, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:contract, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{contract: c} ->
      AuditLog.record(actor.id, :update, "Contract", c.id, %{before: before, after: serialize(c)})
    end)
    |> Repo.transaction()
    |> unwrap(:contract)
  end

  def delete_contract(%Contract{} = contract, %User{} = actor) do
    before = serialize(contract)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:contract, contract)
    |> Ecto.Multi.run(:audit, fn _repo, %{contract: c} ->
      AuditLog.record(actor.id, :delete, "Contract", c.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:contract)
  end

  @doc """
  System-triggered update (advancing `renewal_date` / resetting
  `last_notified_tier`) — used only by `ContractRenewalWorker`, which has no
  authenticated actor. `actor_id` is nil in the audit entry, matching the
  documented "no authenticated actor" case in `Coffer.AuditLog`.
  """
  def system_update_contract(%Contract{} = contract, attrs) do
    before = serialize(contract)
    changeset = Contract.system_changeset(contract, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:contract, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{contract: c} ->
      AuditLog.record(nil, :update, "Contract", c.id, %{before: before, after: serialize(c)})
    end)
    |> Repo.transaction()
    |> unwrap(:contract)
  end

  # -- Attachments ---------------------------------------------------------

  def add_attachment(%Contract{} = contract, %Plug.Upload{} = upload, %User{} = actor) do
    if Attachments.allowed?(upload.content_type) do
      relative_path = Attachments.store_upload!("contracts", upload, upload.filename)

      changeset =
        Attachment.changeset(%Attachment{}, %{
          contract_id: contract.id,
          file_path: relative_path,
          original_filename: upload.filename,
          content_type: upload.content_type,
          uploaded_by_id: actor.id
        })

      Ecto.Multi.new()
      |> Ecto.Multi.insert(:attachment, changeset)
      |> Ecto.Multi.run(:audit, fn _repo, %{attachment: a} ->
        AuditLog.record(actor.id, :create, "ContractAttachment", a.id, %{
          after: %{contract_id: a.contract_id, original_filename: a.original_filename}
        })
      end)
      |> Repo.transaction()
      |> unwrap(:attachment)
    else
      {:error, :unsupported_file_type}
    end
  end

  def delete_attachment(%Attachment{} = attachment, %User{} = actor) do
    Ecto.Multi.new()
    |> Ecto.Multi.delete(:attachment, attachment)
    |> Ecto.Multi.run(:audit, fn _repo, %{attachment: a} ->
      AuditLog.record(actor.id, :delete, "ContractAttachment", a.id, %{
        before: %{contract_id: a.contract_id, original_filename: a.original_filename}
      })
    end)
    |> Repo.transaction()
    |> unwrap(:attachment)
  end

  defp serialize(%Contract{} = c) do
    %{
      id: c.id,
      name: c.name,
      vendor_id: c.vendor_id,
      contract_type: c.contract_type,
      start_date: c.start_date,
      end_date: c.end_date,
      renewal_date: c.renewal_date,
      renewal_frequency: c.renewal_frequency,
      amount: Decimal.to_string(c.amount),
      currency_id: c.currency_id,
      budget_envelope_id: c.budget_envelope_id,
      auto_post_to_ledger: c.auto_post_to_ledger,
      status: c.status,
      last_notified_tier: c.last_notified_tier,
      notes: c.notes
    }
  end

  defp unwrap({:ok, %{contract: result}}, :contract), do: {:ok, result}
  defp unwrap({:ok, %{attachment: result}}, :attachment), do: {:ok, result}
  defp unwrap({:error, _failed_op, changeset, _changes}, _key), do: {:error, changeset}
end
