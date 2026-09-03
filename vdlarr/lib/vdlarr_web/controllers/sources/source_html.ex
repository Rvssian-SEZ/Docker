defmodule VdlarrWeb.Sources.SourceHTML do
  use VdlarrWeb, :html

  alias Vdlarr.Utils.CronUtils

  embed_templates "source_html/*"

  @doc """
  Renders a source form.
  """
  attr :changeset, Ecto.Changeset, required: true
  attr :action, :string, required: true
  attr :media_profiles, :list, required: true
  attr :method, :string, required: true
  # Only meaningful at creation - selection_mode isn't directly editable after that (see
  # Sources.create_source/2's delay_automatic_download opt and restore_automatic_downloads/1).
  attr :show_delay_automatic_download, :boolean, default: false

  def source_form(assigns)

  def friendly_index_frequencies do
    [
      {"Only once when first created", -1},
      {"30 minutes", 30},
      {"1 Hour", 60},
      {"3 Hours", 3 * 60},
      {"6 Hours", 6 * 60},
      {"12 Hours", 12 * 60},
      {"Daily (recommended)", 24 * 60},
      {"Weekly", 7 * 24 * 60},
      {"Monthly", 30 * 24 * 60}
    ]
  end

  def friendly_cookie_behaviours do
    [
      {"Disabled", :disabled},
      {"When Needed", :when_needed},
      {"All Operations", :all_operations}
    ]
  end

  def cutoff_date_presets do
    [
      {"7 days", compute_date_offset(7)},
      {"14 days", compute_date_offset(14)},
      {"30 days", compute_date_offset(30)},
      {"60 days", compute_date_offset(60)},
      {"90 days", compute_date_offset(90)},
      {"180 days", compute_date_offset(180)},
      {"365 days", compute_date_offset(365)}
    ]
  end

  def rss_feed_url(conn, source) do
    # NOTE: The reason for this concatenation is to avoid what appears to be a bug in Phoenix
    # See: https://github.com/phoenixframework/phoenix/issues/6033
    url(conn, ~p"/sources/#{source.uuid}/feed") <> ".xml"
  end

  def output_path_template_override_placeholders(media_profiles) do
    media_profiles
    |> Enum.map(&{&1.id, &1.output_path_template})
    |> Map.new()
    |> Phoenix.json_library().encode!()
  end

  def title_filter_regex_help do
    url = "https://github.com/nalgeon/sqlean/blob/main/docs/regexp.md#supported-syntax"
    classes = "underline decoration-bodydark decoration-1 hover:decoration-white"

    """
    A PCRE-compatible regex. Only media with titles that match this regex will be downloaded. <a href="#{url}" class="#{classes}" target="_blank">See here</a> for syntax
    """
  end

  # This is embedded into a single-quoted JS string literal (`JSON.parse('...')`) in
  # source_form.html.heex, so it needs JS-string escaping (not just the HTML-attribute
  # escaping HEEx does automatically) - otherwise a raw `'` surviving in the field's
  # value (eg: after a failed validation, before the form reflects the rejected input
  # back to the user) could break out of that string literal.
  def cron_picker_initial_state(changeset) do
    changeset
    |> Ecto.Changeset.get_field(:index_cron_schedule)
    |> CronUtils.to_picker_state()
    |> Phoenix.json_library().encode!()
    |> Phoenix.HTML.javascript_escape()
  end

  def cron_schedule_help do
    """
    Optional. When set, indexing runs at a fixed time instead of drifting with Index Frequency above.
    Use Daily or Weekly for common schedules, or Custom to enter a cron expression directly
    (e.g. <code>0 */6 * * *</code> for every 6 hours). Interpreted in the server's configured timezone.
    DST transitions are handled on a best-effort basis. Leave blank to use Index Frequency instead
    """
  end

  def output_path_template_override_help do
    help_button_classes = "underline decoration-bodydark decoration-1 hover:decoration-white cursor-pointer"
    help_button = ~s{<span class="#{help_button_classes}" x-on:click="$dispatch('load-template')">Click here</span>}

    """
    Must end with .{{ ext }}. Same rules as Media Profile output path templates. #{help_button} to load your media profile's output template
    """
  end

  defp compute_date_offset(days) do
    timezone = Application.get_env(:vdlarr, :timezone)

    timezone
    |> Timex.now()
    |> Timex.shift(days: -days)
    |> Timex.format!("{YYYY}-{0M}-{0D}")
  end
end
