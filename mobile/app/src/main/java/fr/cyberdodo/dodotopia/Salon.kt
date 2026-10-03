package fr.cyberdodo.dodotopia

import android.content.Context
import android.os.SystemClock
import androidx.lifecycle.MutableLiveData
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

/**
 * Salon en ligne : jouer le même morceau au même instant que les autres joueurs, PC compris.
 * Même protocole que room.py : une WebSocket, un premier message `create` ou `join`, puis l'état
 * complet du salon poussé par le serveur. L'horloge du serveur est estimée par des ping/pong
 * (NTP simplifié) ; le départ est une heure serveur, convertie une seule fois en heure locale.
 *
 * Tout l'état vit sur le fil principal : les messages du réseau y sont reportés avant d'être traités.
 */
object Salon {

    class Joueur(
        val id: Int, val nom: String, val hote: Boolean, val connecte: Boolean,
        val aLeMorceau: Boolean, val pret: Boolean, val statut: String,
        /** Instrument annoncé (identifiant du catalogue PC) : il donne le registre pour répartir les pistes. */
        val instrument: String = "",
    )

    class MorceauSalon(
        val sha: String, val nom: String, val dureeMs: Long,
        /** Décalage en demi-tons choisi par le chef : le même pour tous, pour jouer dans la même tonalité. */
        val tonalite: Int,
        val source: String, val enLigne: Int?,
        /** Les pistes du fichier, annoncées par le chef avec le morceau : la matière de l'Orchestre. */
        val pistes: List<PisteMidi> = emptyList(),
    )

    /** Le fichier du morceau, lu et prêt à être arrangé pour mon clavier. */
    private class Fichier(val sha: String, val notes: List<NoteMidi>, val dureeMs: Long)

    private enum class Moi { LIBRE, ARME, JOUE }

    /** Incrémenté à chaque changement : l'activité et la bulle s'y abonnent puis relisent les champs. */
    val changement = MutableLiveData(0)

    var actif = false; private set
    var enConnexion = false; private set
    var code: String? = null; private set
    var monId = -1; private set
    var hote = false; private set

    /** « lobby », « countdown » ou « playing ». */
    var etat = "lobby"; private set
    var joueurs: List<Joueur> = emptyList(); private set
    var morceau: MorceauSalon? = null; private set
    var message = ""; private set
    var pret = false; private set
    var telechargement = false; private set

    /**
     * Vrai tant qu'on attend de pouvoir rejoindre le morceau en cours : le joueur l'a demandé depuis l'appli,
     * et la lecture partira dès que la bulle sera prête dans le jeu (instrument ouvert, touches calibrées).
     */
    var attenteRejoindre = false; private set

    private lateinit var contexte: Context
    private var socket: WebSocket? = null
    private var generation = 0
    private var premier: JSONObject? = null
    private var siege: String? = null
    private var essais = 0
    private var parties: JSONObject? = null
    private var departMs = 0L
    private var fichier: Fichier? = null
    private var attendu: String? = null
    private var moi = Moi.LIBRE
    private var forcer = false
    private val horloge = Horloge()

    private fun maintenantMs(): Double = SystemClock.elapsedRealtimeNanos() / 1e6

    private fun texte(id: Int, vararg valeurs: Any): String = contexte.getString(id, *valeurs)

    private fun notifier() {
        changement.value = (changement.value ?: 0) + 1
    }

    // ------------------------------------------------------------------ entrer, sortir

    fun creer(context: Context) = ouvrir(context, JSONObject().put("type", "create"))

    fun rejoindre(context: Context, codeSaisi: String) {
        val propre = codeSaisi.uppercase().filter { it.isLetterOrDigit() }
        if (propre.isEmpty()) return
        ouvrir(context, JSONObject().put("type", "join").put("room_code", propre))
    }

    private fun ouvrir(context: Context, message: JSONObject) {
        if (actif || enConnexion) return
        contexte = context.applicationContext
        val jeton = Compte.jeton(contexte)
        if (jeton == null) {
            this.message = texte(R.string.salon_compte_requis)
            notifier()
            return
        }
        premier = message.put("token", jeton).put("name", "")
            .put("instrument", Preferences.instrument(contexte))
            .put("version", Serveur.VERSION_PROTOCOLE)
        siege = null
        essais = 0
        this.message = texte(R.string.salon_connexion)
        connecter()
    }

    private fun connecter() {
        val moiGeneration = ++generation
        enConnexion = true
        notifier()
        socket = Serveur.http.newWebSocket(
            Request.Builder().url(Serveur.adresseWs(contexte)).build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    Serveur.principal.post {
                        if (moiGeneration != generation) return@post
                        val m = JSONObject(premier.toString())
                        // Reprise après coupure : on redemande son siège dans le même salon.
                        if (siege != null && code != null) m.put("type", "join").put("room_code", code).put("seat_token", siege)
                        webSocket.send(m.toString())
                    }
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    val recu = maintenantMs()
                    Serveur.principal.post {
                        if (moiGeneration != generation) return@post
                        try {
                            traiter(JSONObject(text), recu)
                        } catch (e: JSONException) {
                            SpikeLog.log("Salon : message illisible (${e.message})")
                        }
                    }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = perdu()

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = perdu()

                private fun perdu() {
                    Serveur.principal.post { if (moiGeneration == generation) coupure() }
                }
            },
        )
    }

    /** La connexion est tombée sans qu'on l'ait demandé : le serveur garde le siège une minute. */
    private fun coupure() {
        socket = null
        Serveur.principal.removeCallbacks(battement)
        if (!actif || ++essais > ESSAIS_MAX) {
            val raison = if (actif) texte(R.string.salon_perdu) else message.ifEmpty { texte(R.string.erreur_reseau) }
            fermer(raison)
            return
        }
        message = texte(R.string.salon_reconnexion)
        enConnexion = true
        notifier()
        val moiGeneration = generation
        Serveur.principal.postDelayed({ if (moiGeneration == generation) connecter() }, PAUSE_RECONNEXION_MS)
    }

    fun quitter() {
        if (!actif && !enConnexion) return
        envoyer(JSONObject().put("type", "leave"))
        fermer("")
    }

    private fun fermer(raison: String) {
        generation++
        socket?.close(1000, null)
        socket = null
        Serveur.principal.removeCallbacks(battement)
        arreterLocal()
        actif = false
        enConnexion = false
        code = null
        monId = -1
        hote = false
        etat = "lobby"
        joueurs = emptyList()
        morceau = null
        parties = null
        fichier = null
        attendu = null
        pret = false
        telechargement = false
        finAttenteRejoindre()
        horloge.vider()
        message = raison
        notifier()
    }

    private fun envoyer(m: JSONObject) {
        socket?.send(m.toString())
    }

    // ------------------------------------------------------------------ messages du serveur

    private fun traiter(m: JSONObject, recuMs: Double) {
        when (m.optString("type")) {
            "pong" -> horloge.ajouter(m.optDouble("t0"), m.optDouble("t1"), m.optDouble("t2"), recuMs)
            "joined" -> {
                actif = true
                enConnexion = false
                essais = 0
                code = m.optString("room_code")
                monId = m.optInt("player_id", -1)
                siege = m.optString("seat_token").ifEmpty { null }
                hote = m.optBoolean("host")
                message = ""
                SpikeLog.log("Salon $code rejoint (joueur $monId)")
                rafale()
                Serveur.principal.removeCallbacks(battement)
                Serveur.principal.postDelayed(battement, BATTEMENT_MS)
                notifier()
            }
            "state" -> {
                lireEtat(m)
                assurerMorceau()
                if (etat != "playing") finAttenteRejoindre()
                when {
                    etat == "countdown" && moi == Moi.LIBRE && departMs > 0 -> armer()
                    etat == "lobby" && moi != Moi.LIBRE -> {
                        // Le serveur est revenu au repos (morceau fini, arrêt du chef) : on s'arrête aussi.
                        arreterLocal()
                    }
                }
                notifier()
            }
            "start" -> {
                etat = "countdown"
                departMs = m.optLong("start_at_ms")
                m.optJSONObject("song")?.let { morceau = lireMorceau(it) }
                if (m.has("parts")) parties = m.optJSONObject("parts")
                rafale()
                if (moi == Moi.LIBRE) armer()
                notifier()
            }
            "cancelled", "stop" -> {
                finAttenteRejoindre()
                arreterLocal()
                message = texte(if (m.optString("type") == "stop") R.string.salon_arrete else R.string.salon_annule)
                notifier()
            }
            "error" -> {
                val cle = m.optString("code")
                forcer = cle == "not_all_have_song"
                message = m.optString("message").ifEmpty { cle }
                SpikeLog.log("Salon : erreur $cle")
                if (m.optBoolean("fatal")) fermer(message) else notifier()
            }
            "bye" -> fermer(
                when (m.optString("reason")) {
                    "kicked" -> texte(R.string.salon_exclu)
                    "replaced" -> texte(R.string.salon_remplace)
                    "left" -> ""
                    else -> texte(R.string.salon_ferme)
                }
            )
        }
    }

    private fun lireEtat(m: JSONObject) {
        etat = m.optString("state", "lobby")
        hote = m.optInt("host_id", -2) == monId
        departMs = m.optLong("start_at_ms")
        morceau = m.optJSONObject("song")?.let(::lireMorceau)
        parties = m.optJSONObject("parts")
        val liste = ArrayList<Joueur>()
        val tableau = m.optJSONArray("players") ?: JSONArray()
        for (i in 0 until tableau.length()) {
            val j = tableau.optJSONObject(i) ?: continue
            liste.add(
                Joueur(
                    j.optInt("id"), j.optString("name"), j.optBoolean("host"), j.optBoolean("connected"),
                    j.optBoolean("have_song"), j.optBoolean("ready"), j.optString("status"),
                    j.optString("instrument"),
                )
            )
        }
        joueurs = liste
        pret = liste.firstOrNull { it.id == monId }?.pret ?: false
        messagePartieEnCours()
    }

    /** Une partie se joue sans moi : dit si on peut encore la rejoindre. */
    private fun messagePartieEnCours() {
        if (etat != "playing" || moi != Moi.LIBRE || attenteRejoindre) return
        message = texte(if (positionARejoindre() != null) R.string.salon_rejoignable else R.string.salon_en_cours)
    }

    private fun lireMorceau(o: JSONObject): MorceauSalon? {
        val sha = o.optString("sha256")
        if (sha.isEmpty()) return null
        val pistes = ArrayList<PisteMidi>()
        val tableau = o.optJSONArray("tracks") ?: JSONArray()
        for (i in 0 until tableau.length()) {
            val p = tableau.optJSONObject(i) ?: continue
            pistes.add(
                PisteMidi(
                    p.optInt("index"), p.optString("name"), p.optInt("notes"), p.optInt("low"), p.optInt("high"),
                    p.optDouble("mean", 60.0), p.optBoolean("drums"),
                )
            )
        }
        return MorceauSalon(
            sha, o.optString("name"), o.optLong("duration_ms"), o.optInt("key_shift"),
            o.optString("source"), if (o.isNull("online_id")) null else o.optInt("online_id"), pistes,
        )
    }

    // ------------------------------------------------------------------ orchestre

    /** Vrai quand le chef a réparti les pistes entre les joueurs. */
    val orchestre: Boolean get() = parties?.optBoolean("enabled") == true

    /**
     * La partie d'un joueur, si le chef a réparti les pistes : ses pistes et son octave.
     * null : il joue tout le morceau (pas d'orchestre, ou aucune piste donnée à ce siège), comme my_part de room.py.
     */
    fun partie(joueur: Int): Orchestre.Partie? {
        val p = parties ?: return null
        if (!p.optBoolean("enabled")) return null
        val o = p.optJSONObject("parts")?.optJSONObject(joueur.toString()) ?: return null
        val t = o.optJSONArray("tracks") ?: return null
        if (t.length() == 0) return null
        return Orchestre.Partie((0 until t.length()).map { t.optInt(it) }.sorted(), if (o.isNull("octave")) null else o.optInt("octave"))
    }

    /** « Mélodie + Basse » : ce que joue ce joueur, ou "" s'il joue tout le morceau. */
    fun libellePartie(joueur: Int): String {
        val p = partie(joueur) ?: return ""
        return Orchestre.libelle(morceau?.pistes.orEmpty(), p.pistes) { texte(R.string.salon_piste_n, it) }
    }

    /** Chef : répartition automatique des pistes d'après le registre de l'instrument de chacun (propose_parts). */
    fun repartirPistes() {
        val pistes = morceau?.pistes.orEmpty()
        if (pistes.isEmpty()) {
            message = texte(R.string.salon_sans_pistes)
            notifier()
            return
        }
        definirParties(true, Orchestre.proposer(pistes, joueurs.map { Orchestre.siege(it.id, it.instrument) }))
    }

    /** Chef : envoie la répartition complète (set_parts). Refusé par le serveur pendant une partie. */
    fun definirParties(repartir: Boolean, repartition: Map<Int, Orchestre.Partie>) {
        if (!actif || !hote || etat != "lobby") return
        val table = JSONObject()
        for ((joueur, p) in repartition) {
            val pistes = JSONArray()
            for (i in p.pistes.toSortedSet()) pistes.put(i)
            table.put(
                joueur.toString(),
                JSONObject().put("tracks", pistes).put("octave", p.octave?.coerceIn(-2, 2) ?: JSONObject.NULL),
            )
        }
        envoyer(JSONObject().put("type", "set_parts").put("enabled", repartir).put("parts", table))
    }

    /** Chef : change la partie d'un seul joueur ; les autres gardent la leur (ou tout le morceau, sans orchestre). */
    fun definirPartie(joueur: Int, pistes: List<Int>, octave: Int?) {
        val repartition = LinkedHashMap<Int, Orchestre.Partie>()
        for (j in joueurs) partie(j.id)?.let { repartition[j.id] = it }
        if (pistes.isEmpty()) repartition.remove(joueur) else repartition[joueur] = Orchestre.Partie(pistes, octave)
        definirParties(true, repartition)
    }

    /** Chef : fin de l'orchestre, tout le monde rejoue tout le morceau. */
    fun arreterOrchestre() = definirParties(false, emptyMap())

    /** Chef : retire un joueur du salon (kick). */
    fun exclure(joueur: Int) {
        if (!actif || !hote || joueur == monId) return
        envoyer(JSONObject().put("type", "kick").put("player_id", joueur))
    }


    // ------------------------------------------------------------------ le fichier du morceau

    /** Récupère le fichier du morceau courant s'il n'est pas déjà là, puis prévient le serveur. */
    private fun assurerMorceau() {
        val m = morceau
        if (m == null) {
            fichier = null
            attendu = null
            telechargement = false
            return
        }
        if (fichier?.sha == m.sha || attendu == m.sha) return
        attendu = m.sha
        fichier = null
        telechargement = true
        val salon = code
        val jeton = Compte.jeton(contexte)
        Serveur.fil.execute {
            val resultat = try {
                val biblio = Bibliotheque(contexte)
                val local = biblio.parSha(m.sha)
                val octets = if (local != null) {
                    biblio.octets(local.id)
                } else {
                    val chemin = if (m.source == "library" && m.enLigne != null) "/api/songs/${m.enLigne}/download"
                    else "/api/rooms/$salon/song/${m.sha}"
                    // Gardé dans « Mes morceaux » : on pourra le rejouer seul après la partie.
                    Serveur.telecharger(contexte, chemin, jeton, m.sha).also { biblio.ajouter(it, m.nom, m.enLigne, choisir = false) }
                }
                Fichier(m.sha, Midi.lire(octets), m.dureeMs)
            } catch (e: ErreurEnLigne) {
                e.message.orEmpty()
            } catch (e: IOException) {
                texte(R.string.erreur_fichier)
            } catch (e: MidiIllisible) {
                texte(R.string.erreur_fichier)
            }
            Serveur.principal.post {
                if (attendu != m.sha || morceau?.sha != m.sha) return@post
                attendu = null
                telechargement = false
                if (resultat is Fichier) {
                    fichier = resultat
                    envoyer(JSONObject().put("type", "song_status").put("sha256", m.sha).put("have", true))
                    if (etat == "countdown" && moi == Moi.LIBRE && departMs > 0) armer()
                    messagePartieEnCours()
                } else {
                    message = resultat as String
                    envoyer(JSONObject().put("type", "song_status").put("sha256", m.sha).put("have", false))
                }
                notifier()
            }
        }
    }

    // ------------------------------------------------------------------ départ synchronisé

    private fun etatJoueur(statut: String, raison: String? = null) {
        val m = JSONObject().put("type", "player_state").put("status", statut)
        if (raison != null) m.put("reason", raison)
        envoyer(m)
    }

    /** Prépare la lecture pour l'heure de départ du serveur. Sans fichier, sans bulle ou sans calibrage : on regarde. */
    private fun armer() {
        val m = morceau
        val f = fichier
        if (m == null || f == null || f.sha != m.sha) {
            message = texte(R.string.salon_spectateur)
            etatJoueur("no_song")
            return
        }
        val decalage = horloge.decalageMs
        val service = DodoAccessibilityService.instance
        if (decalage == null || service == null) {
            message = texte(if (service == null) R.string.salon_sans_bulle else R.string.salon_horloge)
            etatJoueur("aborted", if (service == null) "bulle" else "horloge")
            return
        }
        val net = avanceRetard(contexte)
        val delai = (departMs - decalage + net - maintenantMs()).toLong()
        if (delai < DELAI_MIN_MS) {
            // Trop tard pour le départ commun : il reste à rejoindre le morceau en marche.
            message = texte(R.string.salon_rejoignable)
            etatJoueur("aborted", "retard")
            return
        }
        if (!service.jouerSalon(m.nom, code.orEmpty(), monArrangement(m, f), delai)) {
            message = texte(R.string.salon_sans_bulle)
            etatJoueur("aborted", "calibrage")
            return
        }
        moi = Moi.ARME
        message = ""
        etatJoueur("armed")
        SpikeLog.log(
            "Salon : départ dans $delai ms · horloge ${horloge.decalageMs?.toLong()} ms · " +
                "aller-retour ${horloge.allerRetourMs?.toInt()} ms · avance/retard $net ms"
        )
        Serveur.principal.postDelayed(depart, delai)
    }

    /** Le morceau arrangé pour mon clavier : ma partie d'orchestre si le chef en a donné une, la tonalité du salon. */
    private fun monArrangement(m: MorceauSalon, f: Fichier): Arrangement {
        val partie = partie(monId)
        val notes = if (partie == null) f.notes else f.notes.filter { it.piste in partie.pistes }
        return Arrangeur.arranger(notes, Preferences.disposition(contexte), m.tonalite, partie?.octave ?: 0, f.dureeMs)
    }

    private val depart = Runnable {
        if (moi == Moi.ARME) {
            moi = Moi.JOUE
            etatJoueur("playing")
        }
    }

    /** Appelé par la bulle : le morceau est allé au bout, ou le joueur l'a interrompu. */
    fun finLecture(termine: Boolean) {
        if (moi == Moi.LIBRE) return
        Serveur.principal.removeCallbacks(depart)
        moi = Moi.LIBRE
        etatJoueur(if (termine) "ended" else "aborted", if (termine) null else "stop")
        if (!termine) messagePartieEnCours()
        notifier()
    }

    private fun arreterLocal() {
        Serveur.principal.removeCallbacks(depart)
        if (moi == Moi.LIBRE) return
        moi = Moi.LIBRE
        DodoAccessibilityService.instance?.arreterSalon()
    }

    // ------------------------------------------------------------------ rejoindre un morceau en marche

    /**
     * Le salon joue sans moi (arrivé en retard, arrêté par erreur) : la position des autres dans le morceau,
     * en millisecondes, ou null si on ne peut pas les rejoindre (rejoin_position de room.py).
     */
    fun positionARejoindre(): Long? {
        val m = morceau ?: return null
        val f = fichier ?: return null
        val decalage = horloge.decalageMs ?: return null
        if (!actif || etat != "playing" || moi != Moi.LIBRE || departMs <= 0 || f.sha != m.sha) return null
        val position = (maintenantMs() - debutLocalMs(decalage)).toLong()
        if (position < 0 || (m.dureeMs > 0 && position > m.dureeMs - MARGE_FIN_MS)) return null
        return position
    }

    /** Heure locale (même horloge que [maintenantMs]) à laquelle le morceau a commencé pour moi. */
    private fun debutLocalMs(decalage: Double): Double = departMs - decalage + avanceRetard(contexte)

    /**
     * Reprend la lecture là où en sont les autres : on démarre dans [avanceMs] à la position qu'ils auront
     * atteinte à cet instant. Si la bulle n'est pas prête (appli au premier plan, instrument pas ouvert,
     * clavier pas calibré pour cet écran), la demande reste en attente et repart seule dès que possible.
     * Rend vrai si la lecture est armée tout de suite.
     */
    fun rejoindreLecture(avanceMs: Long = AVANCE_REJOINDRE_MS): Boolean {
        if (positionARejoindre() == null) {
            finAttenteRejoindre()
            message = texte(R.string.salon_rejoindre_impossible)
            notifier()
            return false
        }
        if (tenterRejoindre(avanceMs)) {
            finAttenteRejoindre()
            notifier()
            return true
        }
        if (positionARejoindre() == null) {
            // Trop près de la fin pour l'avance demandée.
            finAttenteRejoindre()
            message = texte(R.string.salon_rejoindre_impossible)
            notifier()
            return false
        }
        attenteRejoindre = true
        message = texte(R.string.salon_rejoindre_attente)
        Serveur.principal.removeCallbacks(essaiRejoindre)
        Serveur.principal.postDelayed(essaiRejoindre, ESSAI_REJOINDRE_MS)
        notifier()
        return false
    }

    /** Le joueur renonce à rejoindre le morceau en cours. */
    fun annulerRejoindre() {
        if (!attenteRejoindre) return
        finAttenteRejoindre()
        messagePartieEnCours()
        notifier()
    }

    private fun finAttenteRejoindre() {
        attenteRejoindre = false
        Serveur.principal.removeCallbacks(essaiRejoindre)
    }

    private val essaiRejoindre = object : Runnable {
        override fun run() {
            if (!attenteRejoindre) return
            if (positionARejoindre() == null) {
                finAttenteRejoindre()
                messagePartieEnCours()
                notifier()
                return
            }
            if (tenterRejoindre(AVANCE_REJOINDRE_MS)) {
                finAttenteRejoindre()
                notifier()
            } else {
                Serveur.principal.postDelayed(this, ESSAI_REJOINDRE_MS)
            }
        }
    }

    /** Arme la lecture à la position qu'auront les autres dans [avanceMs]. Faux si la bulle ne peut pas jouer maintenant. */
    private fun tenterRejoindre(avanceMs: Long): Boolean {
        val m = morceau ?: return false
        val f = fichier ?: return false
        val decalage = horloge.decalageMs ?: return false
        val service = DodoAccessibilityService.instance ?: return false
        // Sans touches calibrées pour cet écran (appli en portrait, jeu en paysage), inutile d'arranger le morceau.
        if (Preferences.touches(contexte, Preferences.disposition(contexte)) == null) return false
        val position = (maintenantMs() + avanceMs - debutLocalMs(decalage)).toLong()
        if (position < 0 || position > f.dureeMs - MARGE_FIN_MS) return false
        val suite = monArrangement(m, f).depuis(position)
        if (suite.frappes.isEmpty() || !service.jouerSalon(m.nom, code.orEmpty(), suite, avanceMs)) return false
        moi = Moi.ARME
        message = ""
        etatJoueur("armed")
        SpikeLog.log("Salon : on rejoint la lecture à $position ms (départ dans $avanceMs ms)")
        Serveur.principal.postDelayed(depart, avanceMs)
        return true
    }

    // ------------------------------------------------------------------ avance / retard

    /**
     * Réglage personnel ajouté à l'heure de départ (net_offset_ms du PC), de −300 à +300 ms :
     * positif si on s'entend en avance sur les autres, négatif si on s'entend en retard.
     */
    fun avanceRetard(context: Context): Int =
        Preferences.prefs(context).getInt(AVANCE_RETARD, 0).coerceIn(-AVANCE_RETARD_MAX, AVANCE_RETARD_MAX)

    fun definirAvanceRetard(context: Context, ms: Int): Int {
        val borne = ms.coerceIn(-AVANCE_RETARD_MAX, AVANCE_RETARD_MAX)
        Preferences.prefs(context).edit().putInt(AVANCE_RETARD, borne).apply()
        return borne
    }

    // ------------------------------------------------------------------ actions du joueur

    fun basculerPret() {
        if (actif && etat == "lobby") envoyer(JSONObject().put("type", "ready").put("ready", !pret))
    }

    /** Chef : lance le compte à rebours. Un second appui passe outre « tout le monde n'a pas le morceau ». */
    fun lancer() {
        if (!actif || !hote) return
        val m = JSONObject().put("type", "start")
        if (forcer) m.put("force", true)
        forcer = false
        envoyer(m)
    }

    /** Chef : annule le compte à rebours ou arrête la partie pour tout le monde. */
    fun arreter() {
        if (!actif || !hote) return
        envoyer(JSONObject().put("type", if (etat == "countdown") "cancel" else "stop"))
    }

    /** Chef : choisit le morceau du salon. Un morceau absent de la bibliothèque en ligne est envoyé au salon. */
    fun choisirMorceau(m: Morceau) {
        if (!actif || !hote || etat != "lobby") return
        val salon = code ?: return
        val jeton = Compte.jeton(contexte) ?: return
        message = texte(R.string.salon_envoi)
        notifier()
        Serveur.fil.execute {
            val erreur = try {
                val octets = Bibliotheque(contexte).octets(m.id)
                val lu = Midi.analyser(octets)
                val sha = Bibliotheque.sha256(octets)
                val source = if (m.enLigne != null) "library" else "room"
                if (source == "room") Serveur.deposer(contexte, "/api/rooms/$salon/song", jeton, m.titre, octets)
                val pistes = JSONArray()
                for (p in lu.pistes.take(64)) {
                    pistes.put(
                        JSONObject().put("index", p.index).put("name", p.nom).put("notes", p.notes)
                            .put("low", p.bas).put("high", p.haut).put("mean", Math.round(p.moyenne * 10) / 10.0)
                            .put("drums", p.percussions)
                    )
                }
                val message = JSONObject().put("type", "set_song").put("sha256", sha).put("name", m.titre.take(120))
                    .put("duration_ms", m.dureeMs.coerceAtLeast(1)).put("key_shift", Arrangeur.tonaliteCommune(lu.notes))
                    .put("source", source).put("tracks", pistes)
                if (m.enLigne != null) message.put("online_id", m.enLigne)
                Serveur.principal.post { envoyer(message) }
                ""
            } catch (e: ErreurEnLigne) {
                e.message.orEmpty()
            } catch (e: IOException) {
                texte(R.string.erreur_fichier)
            } catch (e: MidiIllisible) {
                texte(R.string.erreur_fichier)
            }
            Serveur.principal.post {
                message = erreur
                notifier()
            }
        }
    }

    // ------------------------------------------------------------------ horloge

    private val battement = object : Runnable {
        override fun run() {
            ping()
            Serveur.principal.postDelayed(this, BATTEMENT_MS)
        }
    }

    private fun ping() = envoyer(JSONObject().put("type", "ping").put("t0", maintenantMs()))

    /** Quelques mesures rapprochées : à l'entrée dans le salon et au top départ, quand la précision compte. */
    private fun rafale() {
        for (i in 0 until 4) Serveur.principal.postDelayed(::ping, i * 200L)
    }

    /**
     * decalage = heure serveur − heure locale, par la formule NTP. On ne garde que les mesures dont
     * l'aller-retour est proche du meilleur (les autres ont attendu dans une file) et on prend leur médiane.
     */
    private class Horloge {
        private class Mesure(val allerRetour: Double, val decalage: Double)

        private val mesures = ArrayDeque<Mesure>()
        var decalageMs: Double? = null; private set
        var allerRetourMs: Double? = null; private set

        fun ajouter(t0: Double, t1: Double, t2: Double, t3: Double) {
            val allerRetour = (t3 - t0) - (t2 - t1)
            if (allerRetour.isNaN() || allerRetour < 0 || allerRetour > 1000) return
            mesures.addLast(Mesure(allerRetour, ((t1 - t0) + (t2 - t3)) / 2))
            if (mesures.size > 32) mesures.removeFirst()
            val meilleur = mesures.minOf { it.allerRetour }
            val bonnes = mesures.filter { it.allerRetour <= meilleur * 1.5 + 5 }.map { it.decalage }.sorted()
            decalageMs = bonnes[bonnes.size / 2]
            allerRetourMs = meilleur
        }

        fun vider() {
            mesures.clear()
            decalageMs = null
            allerRetourMs = null
        }
    }

    private const val BATTEMENT_MS = 5000L
    private const val PAUSE_RECONNEXION_MS = 3000L
    private const val ESSAIS_MAX = 15

    /** En dessous, le départ commun est déjà là : il reste [rejoindreLecture]. */
    private const val DELAI_MIN_MS = 300L

    /** Rejoindre un morceau en marche : le temps que la carte s'affiche et que le menu se replie (3 s depuis l'interface du PC). */
    private const val AVANCE_REJOINDRE_MS = 3000L
    private const val ESSAI_REJOINDRE_MS = 1000L

    /** Trop près de la fin : rien à rejoindre. */
    private const val MARGE_FIN_MS = 2000L

    private const val AVANCE_RETARD = "salon_avance_retard_ms"
    const val AVANCE_RETARD_MAX = 300
}
