/**
 *  Plex Webhook Lighting
 *
 *  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
 *  in compliance with the License. You may obtain a copy of the License at:
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 *  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License
 *  for the specific language governing permissions and limitations under the License.
 *
 *  Receives Plex Media Server webhooks (requires Plex Pass) and controls lights when playback
 *  starts, pauses, resumes or stops.
 *
 *  Setup:
 *    1. In the IDE, enable OAuth for this SmartApp before publishing it.
 *    2. Install the SmartApp and copy the webhook URL shown on the first page.
 *    3. In Plex: Settings > Account > Webhooks > Add Webhook, and paste the URL.
 */

import groovy.json.JsonSlurper

definition(
	name: "Plex Webhook Lighting",
	namespace: "smartthings",
	author: "SmartThings",
	description: "Dim or turn off lights when Plex starts playing, and bring them back when it pauses or stops.",
	category: "Convenience",
	iconUrl: "https://s3.amazonaws.com/smartapp-icons/Convenience/Cat-Convenience.png",
	iconX2Url: "https://s3.amazonaws.com/smartapp-icons/Convenience/Cat-Convenience@2x.png",
	oauth: [displayName: "Plex Webhook Lighting", displayLink: ""]
)

preferences {
	page(name: "mainPage")
}

mappings {
	path("/plex") {
		action: [POST: "handlePlexWebhook"]
	}
}

def mainPage() {
	if (!state.accessToken) {
		try {
			createAccessToken()
		} catch (e) {
			log.error "Unable to create access token. Is OAuth enabled for this SmartApp? ${e}"
		}
	}

	dynamicPage(name: "mainPage", title: "Plex Webhook Lighting", install: true, uninstall: true) {
		section("Plex webhook URL") {
			if (state.accessToken) {
				paragraph "Add this URL in Plex under Settings > Account > Webhooks:\n\n${webhookUrl()}"
			} else {
				paragraph "OAuth is not enabled for this SmartApp. Enable it in the IDE, then open this page again."
			}
		}
		section("Which Plex playback should trigger this?") {
			input "playerNames", "text", title: "Player names (comma-separated, blank = any player)", required: false
			input "accountNames", "text", title: "Plex user names (comma-separated, blank = any user)", required: false
			input "mediaTypes", "enum", title: "Media types", multiple: true, required: false,
				options: ["movie": "Movies", "episode": "TV episodes", "track": "Music", "clip": "Clips / trailers"],
				defaultValue: ["movie", "episode"]
		}
		section("When playing") {
			input "playSwitchesOff", "capability.switch", title: "Turn off these lights", multiple: true, required: false
			input "playDimmers", "capability.switchLevel", title: "Dim these lights", multiple: true, required: false
			input "playLevel", "number", title: "Dim to level (0-100)", range: "0..100", required: false, defaultValue: 10
		}
		section("When paused") {
			input "pauseLevel", "number", title: "Set dimmers to level (0-100, blank = no change)", range: "0..100", required: false, defaultValue: 40
		}
		section("When stopped") {
			input "stopAction", "enum", title: "After playback stops", required: false, defaultValue: "restore",
				options: ["restore": "Restore lights to how they were", "level": "Set dimmers to a level", "none": "Do nothing"]
			input "stopLevel", "number", title: "Level for 'Set dimmers to a level' (0-100)", range: "0..100", required: false, defaultValue: 80
		}
		section("Restrictions") {
			input "activeModes", "mode", title: "Only in these modes", multiple: true, required: false
		}
		section([mobileOnly: true]) {
			label title: "Assign a name", required: false
		}
	}
}

def installed() {
	log.debug "Installed with settings: ${settings}"
	initialize()
}

def updated() {
	log.debug "Updated with settings: ${settings}"
	initialize()
}

def initialize() {
	state.playing = state.playing ?: false
}

private String webhookUrl() {
	"${getApiServerUrl()}/api/smartapps/installations/${app.id}/plex?access_token=${state.accessToken}"
}

// ---------------------------------------------------------------------------
// Webhook handling
// ---------------------------------------------------------------------------

def handlePlexWebhook() {
	def payload = parsePayload()
	if (!payload) {
		log.warn "Plex webhook: could not parse payload"
		return [status: "ignored", reason: "unparseable payload"]
	}

	def event = payload.event
	def player = payload.Player?.title
	def account = payload.Account?.title
	def type = payload.Metadata?.type
	log.debug "Plex webhook: event=${event} player=${player} account=${account} type=${type} title=${payload.Metadata?.title}"

	def reason = filterReason(player, account, type)
	if (reason) {
		log.debug "Plex webhook ignored: ${reason}"
		return [status: "ignored", reason: reason]
	}

	switch (event) {
		case "media.play":
		case "media.resume":
			onPlay()
			break
		case "media.pause":
			onPause()
			break
		case "media.stop":
			onStop()
			break
		default:
			return [status: "ignored", reason: "unhandled event ${event}"]
	}
	[status: "ok", event: event]
}

/**
 * Plex sends webhooks as multipart/form-data with the JSON in a "payload" field.
 * Plain application/json bodies are also accepted, which is handy for testing with curl.
 */
private Map parsePayload() {
	try {
		if (request.JSON instanceof Map && request.JSON.event) {
			return request.JSON
		}
	} catch (ignored) {
		// Not a JSON request; fall through to multipart parsing.
	}

	def body = request.body
	if (body == null) {
		return null
	}
	String text = (body instanceof byte[]) ? new String(body, "UTF-8") : body.toString()
	int start = text.indexOf("{")
	int end = text.lastIndexOf("}")
	if (start < 0 || end <= start) {
		return null
	}
	try {
		def parsed = new JsonSlurper().parseText(text.substring(start, end + 1))
		return (parsed instanceof Map) ? parsed : null
	} catch (e) {
		log.warn "Plex webhook: JSON parse error ${e}"
		return null
	}
}

private String filterReason(String player, String account, String type) {
	if (activeModes && !(location.mode in activeModes)) {
		return "mode ${location.mode} not selected"
	}
	def players = splitList(playerNames)
	if (players && !(player?.toLowerCase() in players)) {
		return "player ${player} not selected"
	}
	def accounts = splitList(accountNames)
	if (accounts && !(account?.toLowerCase() in accounts)) {
		return "account ${account} not selected"
	}
	def types = mediaTypes ? (mediaTypes instanceof Collection ? mediaTypes : [mediaTypes]) : ["movie", "episode"]
	if (type && !(type in types)) {
		return "media type ${type} not selected"
	}
	null
}

private List splitList(String value) {
	value ? value.split(",")*.trim().findAll { it }*.toLowerCase() : []
}

// ---------------------------------------------------------------------------
// Light control
// ---------------------------------------------------------------------------

private void onPlay() {
	if (!state.playing) {
		saveLightState()
	}
	state.playing = true
	playSwitchesOff?.off()
	if (playDimmers) {
		setLevel(playDimmers, playLevel != null ? playLevel : 10)
	}
}

private void onPause() {
	if (playDimmers && pauseLevel != null) {
		setLevel(playDimmers, pauseLevel)
	}
}

private void onStop() {
	def action = stopAction ?: "restore"
	if (action == "restore") {
		restoreLightState()
	} else if (action == "level") {
		playSwitchesOff?.on()
		if (playDimmers) {
			setLevel(playDimmers, stopLevel != null ? stopLevel : 80)
		}
	}
	state.playing = false
	state.saved = null
}

private void setLevel(devices, level) {
	int lvl = Math.max(0, Math.min(100, level as Integer))
	devices.each { d ->
		if (lvl == 0) {
			d.off()
		} else {
			d.setLevel(lvl)
		}
	}
}

private void saveLightState() {
	def saved = [:]
	playSwitchesOff?.each { d ->
		saved[d.id] = [switch: d.currentValue("switch")]
	}
	playDimmers?.each { d ->
		def entry = saved[d.id] ?: [:]
		entry.switch = d.currentValue("switch")
		entry.level = d.currentValue("level")
		saved[d.id] = entry
	}
	state.saved = saved
}

private void restoreLightState() {
	def saved = state.saved ?: [:]
	def devices = ((playSwitchesOff ?: []) + (playDimmers ?: [])).unique { it.id }
	devices.each { d ->
		def s = saved[d.id]
		if (!s) {
			return
		}
		if (s.switch == "on") {
			if (s.level != null && d.hasCommand("setLevel")) {
				d.setLevel(s.level as Integer)
			}
			d.on()
		} else {
			d.off()
		}
	}
}
