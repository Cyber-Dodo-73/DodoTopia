package fr.cyberdodo.dodotopia

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.util.Base64
import androidx.lifecycle.MutableLiveData
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.security.SecureRandom
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Refus ou panne côté serveur. [message] est affichable tel quel ; [cle] est le code du serveur (« room_full »…). */
class ErreurEnLigne(
    message: String, val code: Int = 0, val cle: String = "",
    /** Pour « duplicate » : le numéro du morceau déjà présent dans la bibliothèque en ligne. */
    val existant: Int? = null,
) : Exception(message)

class Utilisateur(val id: Int, val nom: String)

/**
 * Appels au serveur DodoTopia : mêmes points d'entrée et mêmes formats que online.py côté PC.
 * Tout est bloquant : à appeler depuis [fil], jamais depuis le fil principal.
 */
object Serveur {
    private const val ADRESSE = "https://dodotopia.cyber-dodo.fr"

    /** Version du protocole des salons que parle cette appli : celle du client PC dont il est repris. */
    const val VERSION_PROTOCOLE = "2.1.0"
    const val MORCEAU_MAX = 8 * 1024 * 1024

    private val JSON = "application/json; charset=utf-8".toMediaType()
    private val MIDI = "audio/midi".toMediaType()
    val agent = "DodoTopia-Mobile/${BuildConfig.VERSION_NAME} (android)"

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    val fil: ExecutorService = Executors.newCachedThreadPool()
    val principal = Handler(Looper.getMainLooper())

    /** L'adresse du serveur. Seules les versions de test acceptent d'en changer (serveur local). */
    fun adresse(context: Context): String =
        if (BuildConfig.DEBUG) Preferences.prefs(context).getString("serveur", null) ?: ADRESSE else ADRESSE

    fun adresseWs(context: Context): String = adresse(context).replaceFirst("http", "ws") + "/ws"

    private fun requete(context: Context, chemin: String, jeton: String?): Request.Builder {
        val r = Request.Builder().url(adresse(context) + chemin)
            .header("User-Agent", agent).header("Accept", "application/json")
        if (jeton != null) r.header("Authorization", "Bearer $jeton")
        return r
    }

    @Throws(ErreurEnLigne::class)
    fun lire(context: Context, chemin: String, jeton: String? = null): JSONObject =
        executer(context, requete(context, chemin, jeton).get().build())

    @Throws(ErreurEnLigne::class)
    fun envoyer(context: Context, chemin: String, corps: JSONObject, jeton: String? = null): JSONObject =
        executer(context, requete(context, chemin, jeton).post(corps.toString().toRequestBody(JSON)).build())

    /** Dépôt d'un fichier MIDI (morceau éphémère d'un salon). */
    @Throws(ErreurEnLigne::class)
    fun deposer(context: Context, chemin: String, jeton: String, titre: String, octets: ByteArray): JSONObject {
        val corps = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("title", titre)
            .addFormDataPart("file", "morceau.mid", octets.toRequestBody(MIDI))
            .build()
        return executer(context, requete(context, chemin, jeton).post(corps).build())
    }

    /** Télécharge un fichier et vérifie son empreinte : un fichier qui ne correspond pas est refusé. */
    @Throws(ErreurEnLigne::class)
    fun telecharger(context: Context, chemin: String, jeton: String?, sha256: String): ByteArray {
        val octets = try {
            http.newCall(requete(context, chemin, jeton).header("Accept", "audio/midi").get().build()).execute().use { r ->
                if (!r.isSuccessful) throw erreur(context, r.code, r.body?.string().orEmpty())
                val lu = r.body!!.byteStream().lireAuPlus(MORCEAU_MAX + 1)
                if (lu.size > MORCEAU_MAX) throw ErreurEnLigne(context.getString(R.string.erreur_fichier))
                lu
            }
        } catch (e: IOException) {
            SpikeLog.log("Réseau : ${e.javaClass.simpleName} ${e.message}")
            throw ErreurEnLigne(context.getString(R.string.erreur_reseau))
        }
        if (Bibliotheque.sha256(octets) != sha256.lowercase()) throw ErreurEnLigne(context.getString(R.string.erreur_fichier))
        return octets
    }

    private fun executer(context: Context, requete: Request): JSONObject {
        try {
            http.newCall(requete).execute().use { r ->
                val texte = r.body?.string().orEmpty()
                if (!r.isSuccessful) throw erreur(context, r.code, texte)
                return if (texte.isBlank()) JSONObject() else JSONObject(texte)
            }
        } catch (e: IOException) {
            SpikeLog.log("Réseau : ${e.javaClass.simpleName} ${e.message}")
            throw ErreurEnLigne(context.getString(R.string.erreur_reseau))
        } catch (e: JSONException) {
            throw ErreurEnLigne(context.getString(R.string.erreur_serveur, 0))
        }
    }

    /** Les erreurs du serveur ont la forme {"detail": {code, message}}. */
    private fun erreur(context: Context, statut: Int, texte: String): ErreurEnLigne {
        val detail = try {
            JSONObject(texte).optJSONObject("detail")
        } catch (e: JSONException) {
            null
        }
        val message = detail?.optString("message").orEmpty()
        return ErreurEnLigne(
            when {
                statut == 429 -> context.getString(R.string.erreur_trop)
                message.isNotEmpty() -> message
                else -> context.getString(R.string.erreur_serveur, statut)
            },
            statut, detail?.optString("code").orEmpty(),
            if (detail != null && detail.has("existing_id") && !detail.isNull("existing_id")) detail.optInt("existing_id") else null,
        )
    }

    // ------------------------------------------------------------------ bibliothèque : j'aime, partage

    /** Les tags qu'accepte le serveur (SONG_TAGS de schemas.py), dans son ordre ; leurs noms sont dans R.array.tags_noms. */
    val TAGS = listOf(
        "piano", "flute", "lute", "violin", "harp", "percussion", "pop", "rock", "classique", "jeu-video",
        "anime", "film", "folk", "noel", "calme", "rapide", "facile", "difficile",
    )
    const val TAGS_MAX = 8

    /** Licences d'un morceau partagé (LICENSES de schemas.py) ; leurs noms sont dans R.array.licences_noms. */
    val LICENCES = listOf("own", "public_domain", "cc", "unknown")

    /** Instruments du catalogue, pour filtrer la bibliothèque ; leurs noms sont dans R.array.instruments_noms. */
    val INSTRUMENTS = listOf(
        "piano", "recorder", "xiao", "lute", "wooden-bass", "bagpipe", "concertina", "mbira", "lyre", "violin",
        "cello", "conga", "cajon", "xylophone", "saxophone", "harp", "steel-tongue-drum", "ocarina", "conch",
    )

    /** Aime un morceau, ou retire son j'aime. Rend le nouveau nombre de j'aime. Compte requis. */
    @Throws(ErreurEnLigne::class)
    fun aimer(context: Context, numero: Int, jeton: String, aime: Boolean): Int {
        val r = requete(context, "/api/songs/$numero/like", jeton)
        val reponse = executer(context, (if (aime) r.post(ByteArray(0).toRequestBody(null)) else r.delete()).build())
        return reponse.optInt("likes").coerceAtLeast(0)
    }

    /**
     * Dépose un morceau dans la bibliothèque en ligne (file de modération). Rend le morceau créé : son « id »
     * est son numéro en ligne. Un fichier déjà présent lève une erreur « duplicate » qui porte ce numéro.
     */
    @Throws(ErreurEnLigne::class)
    fun partager(
        context: Context, jeton: String, titre: String, octets: ByteArray,
        tags: List<String>, instrument: String, licence: String,
    ): JSONObject {
        val propres = tags.filter { it in TAGS }.distinct().take(TAGS_MAX)
        val corps = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("title", titre.trim().take(120))
            .addFormDataPart("tags", JSONArray(propres).toString())
            .addFormDataPart("instrument", if (instrument in INSTRUMENTS) instrument else "")
            .addFormDataPart("source_url", "")
            .addFormDataPart("source_name", "")
            .addFormDataPart("license", if (licence in LICENCES) licence else "unknown")
            .addFormDataPart("file", nomDeFichier(titre), octets.toRequestBody(MIDI))
            .build()
        return executer(context, requete(context, "/api/songs", jeton).post(corps).build())
    }

    /** « Mon morceau ! » devient « Mon_morceau.mid » : le serveur garde ce nom pour l'afficher, jamais comme chemin. */
    private fun nomDeFichier(titre: String): String {
        val base = titre.trim().map { if (it.isLetterOrDigit() || it == '-') it else '_' }.joinToString("")
            .replace(Regex("_+"), "_").trim('_').take(60)
        return base.ifEmpty { "morceau" } + ".mid"
    }
}

/** Le compte Discord connecté : jeton de session et profil, gardés dans un fichier privé à part des réglages. */
object Compte {
    private const val FICHIER = "compte"

    /** null = pas connecté. Observé par l'activité. */
    val utilisateur = MutableLiveData<Utilisateur?>()

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(FICHIER, Context.MODE_PRIVATE)

    fun charger(context: Context) {
        val p = prefs(context)
        val nom = p.getString("nom", null)
        utilisateur.value = if (p.getString("jeton", null) != null && nom != null) Utilisateur(p.getInt("id", 0), nom) else null
    }

    fun jeton(context: Context): String? = prefs(context).getString("jeton", null)

    fun enregistrer(context: Context, jeton: String, profil: JSONObject?) {
        val u = Utilisateur(profil?.optInt("id") ?: 0, profil?.optString("username").orEmpty().ifEmpty { "Discord" })
        prefs(context).edit().putString("jeton", jeton).putInt("id", u.id).putString("nom", u.nom).apply()
        utilisateur.postValue(u)
    }

    /** Déconnexion : la session est aussi fermée côté serveur, sans attendre sa réponse. */
    fun deconnecter(context: Context) {
        val jeton = jeton(context)
        prefs(context).edit().clear().apply()
        utilisateur.value = null
        if (jeton != null) {
            val app = context.applicationContext
            Serveur.fil.execute {
                try {
                    Serveur.envoyer(app, "/api/auth/logout", JSONObject(), jeton)
                } catch (e: ErreurEnLigne) {
                    // Session déjà close ou serveur injoignable : l'appli, elle, a oublié le jeton.
                }
            }
        }
    }
}

/**
 * Connexion Discord, comme sur PC : le serveur donne un ticket, la page s'ouvre dans le navigateur
 * (elle demande le code affiché dans l'appli avant de passer chez Discord), et l'appli interroge
 * le serveur jusqu'à ce que la connexion soit faite. Aucun mot de passe ne passe par l'appli.
 */
object Connexion {
    class Etat(val enCours: Boolean, val code: String? = null, val adresse: String? = null, val erreur: String? = null)

    val etat = MutableLiveData(Etat(false))

    private const val PAUSE_MS = 1500L
    private const val DUREE_MAX_S = 600L

    @Volatile
    private var tentative = 0

    fun demarrer(context: Context) {
        val app = context.applicationContext
        val moi = ++tentative
        etat.value = Etat(true)
        Serveur.fil.execute {
            try {
                val alea = ByteArray(32).also { SecureRandom().nextBytes(it) }
                val verifieur = Base64.encodeToString(alea, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
                val ticket = Serveur.envoyer(
                    app, "/api/auth/start",
                    JSONObject().put("verifier_hash", Bibliotheque.sha256(verifieur.toByteArray(Charsets.US_ASCII))),
                )
                val id = ticket.getString("login_id")
                val adresse = ticket.getString("url")
                val code = ticket.optString("user_code").uppercase().take(16).ifEmpty { null }
                if (moi != tentative) return@execute
                etat.postValue(Etat(true, code, adresse))
                Serveur.principal.post { ouvrir(app, adresse) }

                val fin = System.currentTimeMillis() + minOf(ticket.optLong("expires_in", DUREE_MAX_S), DUREE_MAX_S) * 1000
                while (moi == tentative) {
                    if (System.currentTimeMillis() > fin) throw ErreurEnLigne(app.getString(R.string.connexion_expiree))
                    Thread.sleep(PAUSE_MS)
                    val r = try {
                        Serveur.envoyer(app, "/api/auth/poll", JSONObject().put("login_id", id).put("verifier", verifieur))
                    } catch (e: ErreurEnLigne) {
                        if (e.code == 404 || e.code == 410 || e.code == 403) throw ErreurEnLigne(app.getString(R.string.connexion_expiree))
                        continue    // panne passagère : on réessaie au tour suivant
                    }
                    when (r.optString("status")) {
                        "ok" -> {
                            if (moi != tentative) return@execute
                            Compte.enregistrer(app, r.getString("token"), r.optJSONObject("user"))
                            etat.postValue(Etat(false))
                            SpikeLog.log("Compte : connecté")
                            return@execute
                        }
                        "error" -> throw ErreurEnLigne(app.getString(R.string.connexion_refusee))
                    }
                }
            } catch (e: ErreurEnLigne) {
                if (moi == tentative) etat.postValue(Etat(false, erreur = e.message))
            } catch (e: JSONException) {
                if (moi == tentative) etat.postValue(Etat(false, erreur = app.getString(R.string.erreur_serveur, 0)))
            } catch (e: InterruptedException) {
                // Appli fermée pendant l'attente.
            }
        }
    }

    fun annuler() {
        tentative++
        etat.value = Etat(false)
    }

    fun ouvrir(context: Context, adresse: String) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(adresse)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: RuntimeException) {
            // Pas de navigateur : l'adresse reste affichée dans l'appli, à recopier.
        }
    }
}
