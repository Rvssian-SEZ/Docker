defmodule VdlarrWeb.Settings.SettingHTML do
  use VdlarrWeb, :html

  embed_templates "setting_html/*"

  @doc """
  Renders a setting form.
  """
  attr :conn, Plug.Conn, required: true
  attr :changeset, Ecto.Changeset, required: true
  attr :action, :string, required: true

  def setting_form(assigns)

  def apprise_server_help do
    url = "https://github.com/caronc/apprise/wiki/URLBasics"

    ~s(Server endpoint for Apprise notifications when new media is found. See <a href="#{url}" class="#{help_link_classes()}" target="_blank">Apprise docs</a> for more information)
  end

  def yt_dlp_update_policy_help do
    "Which yt-dlp build to track. Frozen/pinned options re-assert their target on every boot, since the binary lives on the container's ephemeral filesystem and reverts to whatever's baked into the image otherwise"
  end

  @timezone_region_labels %{
    africa: "Africa",
    antarctica: "Antarctica",
    asia: "Asia",
    australasia: "Australia & Pacific",
    etcetera: "UTC & Fixed Offsets",
    europe: "Europe",
    northamerica: "North America",
    southamerica: "South America"
  }

  def timezone_options do
    Tzdata.zone_lists_grouped()
    |> Enum.reject(fn {region, _zones} -> region == :backward end)
    |> Enum.map(fn {region, zones} -> {Map.get(@timezone_region_labels, region, to_string(region)), Enum.sort(zones)} end)
    |> Enum.sort_by(&elem(&1, 0))
  end

  def diagnostic_info_string do
    """
    - App Version: #{Application.spec(:vdlarr)[:vsn]}
    - yt-dlp Version: #{Settings.get!(:yt_dlp_version)}
    - yt-dlp Update Behavior: #{Vdlarr.YtDlp.UpdateManager.humanize_policy(Settings.get!(:yt_dlp_update_policy))}
    - Apprise Version: #{Settings.get!(:apprise_version)}
    - System Architecture: #{to_string(:erlang.system_info(:system_architecture))}
    - Timezone: #{Application.get_env(:vdlarr, :timezone)}
    """
  end

  defp help_link_classes do
    "underline decoration-bodydark decoration-1 hover:decoration-white"
  end
end
