package fr.cyberdodo.dodotopia

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID

class Morceau(
    val id: String, val titre: String, val dureeMs: Long, val nbNotes: Int,
    /** Empreinte du fichier : c'est elle qui identifie un morceau dans un salon et dans la bibliothèque en ligne. */
    val sha256: String = "",
    /** Numéro du morceau dans la bibliothèque en ligne, s'il en vient. */
    val enLigne: Int? = null,
) {
    val demo: Boolean get() = id.startsWith(Bibliotheque.PREFIXE_DEMO)
}

/**
 * Les morceaux de l'appli : les MIDI importés ou téléchargés (copiés dans filesDir/morceaux, index dans
 * les préférences) suivis de trois airs d'exemple, pour qu'on puisse essayer sans rien importer.
 * L'activité, le service et le salon en créent chacun une : tout est relu depuis le disque à chaque appel.
 */
class Bibliotheque(context: Context) {

    private val contexte = context.applicationContext
    private val prefs = Preferences.prefs(contexte)
    private val dossier = File(contexte.filesDir, "morceaux")

    init {
        // L'activité, la bulle et le salon créent chacun leur bibliothèque avant d'arranger quoi que ce soit.
        Arrangeur.melodieParDefaut = arrangeur(contexte)
    }

    fun liste(): List<Morceau> = importes() + DEMOS.map { it.morceau }

    private fun importes(): List<Morceau> {
        val sortie = ArrayList<Morceau>()
        val index = try {
            JSONArray(prefs.getString(INDEX, "[]"))
        } catch (e: org.json.JSONException) {
            JSONArray()
        }
        for (i in 0 until index.length()) {
            val o = index.optJSONObject(i) ?: continue
            sortie.add(
                Morceau(
                    o.optString("id"), o.optString("titre"), o.optLong("duree"), o.optInt("notes"),
                    o.optString("sha"), if (o.has("en_ligne")) o.optInt("en_ligne") else null,
                )
            )
        }
        return sortie
    }

    private fun ecrire(morceaux: List<Morceau>) {
        val index = JSONArray()
        for (m in morceaux) {
            val o = JSONObject().put("id", m.id).put("titre", m.titre).put("duree", m.dureeMs)
                .put("notes", m.nbNotes).put("sha", m.sha256)
            if (m.enLigne != null) o.put("en_ligne", m.enLigne)
            index.put(o)
        }
        prefs.edit().putString(INDEX, index.toString()).apply()
    }

    /** Le morceau à jouer : le dernier choisi, sinon le premier de la liste. */
    fun choisi(): Morceau {
        val tous = liste()
        val id = prefs.getString(CHOISI, null)
        return tous.firstOrNull { it.id == id } ?: tous[0]
    }

    fun choisir(id: String) = prefs.edit().putString(CHOISI, id).apply()

    fun parId(id: String): Morceau? = liste().firstOrNull { it.id == id }

    fun parSha(sha: String): Morceau? = liste().firstOrNull { it.sha256 == sha }

    fun parNumeroEnLigne(numero: Int): Morceau? = importes().firstOrNull { it.enLigne == numero }

    /** Le fichier MIDI d'un morceau (les airs d'exemple sont écrits à la volée). */
    @Throws(IOException::class)
    fun octets(id: String): ByteArray {
        DEMOS.firstOrNull { it.morceau.id == id }?.let { return it.octets }
        return File(dossier, "$id.mid").readBytes()
    }

    /** Les notes à jouer seul : celles du fichier, moins les pistes que l'utilisateur a coupées pour ce morceau. */
    @Throws(IOException::class, MidiIllisible::class)
    fun notes(id: String): List<NoteMidi> = Midi.sansPistes(Midi.lire(octets(id)), pistesCoupees(id))

    /** Les pistes du fichier qui ont des notes jouables (les percussions seules sont écartées, comme à la lecture). */
    @Throws(IOException::class, MidiIllisible::class)
    fun pistes(id: String): List<PisteMidi> = Midi.analyser(octets(id)).pistes.filter { !it.percussions }

    /** Indices des pistes coupées pour ce morceau (skip_tracks côté PC). Vide : tout est joué. */
    fun pistesCoupees(id: String): Set<Int> =
        prefs.getString(PISTES + id, null).orEmpty().split(',').mapNotNull { it.toIntOrNull() }.toSet()

    fun definirPistesCoupees(id: String, coupees: Set<Int>) {
        val edition = prefs.edit()
        if (coupees.isEmpty()) edition.remove(PISTES + id) else edition.putString(PISTES + id, coupees.sorted().joinToString(","))
        edition.apply()
    }

    /** Copie le fichier dans l'appli après avoir vérifié qu'il se lit, puis le choisit. */
    @Throws(IOException::class, MidiIllisible::class)
    fun importer(uri: Uri): Morceau {
        val octets = contexte.contentResolver.openInputStream(uri)?.use { flux ->
            val tampon = flux.lireAuPlus(TAILLE_MAX + 1)
            if (tampon.size > TAILLE_MAX) throw MidiIllisible("fichier trop gros")
            tampon
        } ?: throw IOException("fichier inaccessible")
        return ajouter(octets, titre(uri), null)
    }

    /**
     * Ajoute un fichier déjà en mémoire (téléchargé de la bibliothèque en ligne ou reçu d'un salon).
     * Un fichier déjà présent n'est pas dupliqué : on rend l'existant, en notant son numéro en ligne.
     */
    @Throws(IOException::class, MidiIllisible::class)
    fun ajouter(octets: ByteArray, titre: String, enLigne: Int?, choisir: Boolean = true): Morceau {
        val sha = sha256(octets)
        val connus = importes()
        connus.firstOrNull { it.sha256 == sha }?.let { deja ->
            if (enLigne != null && deja.enLigne != enLigne) {
                ecrire(connus.map { if (it.id == deja.id) Morceau(it.id, it.titre, it.dureeMs, it.nbNotes, it.sha256, enLigne) else it })
            }
            if (choisir) choisir(deja.id)
            return deja
        }
        val notes = Midi.lire(octets)
        val morceau = Morceau(
            UUID.randomUUID().toString(), titre.take(80).ifBlank { "MIDI" },
            notes.maxOf { it.debutMs + it.dureeMs }, notes.size, sha, enLigne,
        )
        dossier.mkdirs()
        File(dossier, "${morceau.id}.mid").writeBytes(octets)
        ecrire(listOf(morceau) + connus)
        if (choisir) choisir(morceau.id)
        return morceau
    }

    fun supprimer(id: String) {
        ecrire(importes().filter { it.id != id })
        File(dossier, "$id.mid").delete()
        prefs.edit().remove(PISTES + id).apply()
    }

    /**
     * Un morceau qu'on vient de partager : on le retient pour ne pas le proposer deux fois. Son numéro en ligne
     * n'est pas noté dans l'index : tant que la modération ne l'a pas validé, personne d'autre ne peut le
     * télécharger par ce numéro, et un salon doit continuer à envoyer le fichier lui-même.
     */
    fun noterPartage(id: String) {
        prefs.edit().putStringSet(PARTAGES, partages() + id).apply()
    }

    private fun partages(): Set<String> = prefs.getStringSet(PARTAGES, null)?.toSet() ?: emptySet()

    /** Les morceaux importés qui ne viennent pas de la bibliothèque en ligne et n'y ont pas déjà été envoyés. */
    fun partageables(): List<Morceau> {
        val deja = partages()
        return importes().filter { it.enLigne == null && it.id !in deja }
    }

    /** « Mon_morceau (1).mid » devient « Mon morceau (1) ». */
    private fun titre(uri: Uri): String {
        var nom: String? = null
        try {
            contexte.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) nom = c.getString(0)
            }
        } catch (e: RuntimeException) {
            // Fournisseur de fichiers capricieux : on se rabat sur la fin de l'adresse.
        }
        val brut = nom ?: uri.lastPathSegment ?: ""
        return brut.substringAfterLast('/')
            .replace(Regex("(\\.midi?)+$", RegexOption.IGNORE_CASE), "")
            .replace('_', ' ')
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private class Demo(id: String, titre: String, val notes: List<NoteMidi>) {
        val octets: ByteArray = Midi.ecrire(notes)
        val morceau = Morceau(PREFIXE_DEMO + id, titre, notes.maxOf { it.debutMs + it.dureeMs }, notes.size, sha256(octets))
    }

    companion object {
        const val PREFIXE_DEMO = "demo:"
        private const val INDEX = "morceaux"
        private const val CHOISI = "morceau_choisi"
        private const val PISTES = "pistes_coupees_"
        private const val ARRANGEUR = "arrangeur"
        private const val PARTAGES = "morceaux_partages"
        const val TAILLE_MAX = 4 * 1024 * 1024

        /**
         * Vrai (par défaut, comme le mode « auto » du PC) : sur un clavier sans dièses, la mélodie est suivie
         * et l'accompagnement allégé. Faux : chaque note est placée seule, comme avant.
         */
        fun arrangeur(context: Context): Boolean = Preferences.prefs(context).getBoolean(ARRANGEUR, true)

        fun definirArrangeur(context: Context, actif: Boolean) {
            Preferences.prefs(context).edit().putBoolean(ARRANGEUR, actif).apply()
            Arrangeur.melodieParDefaut = actif
        }

        fun sha256(octets: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(octets).joinToString("") { "%02x".format(it) }

        /** Hauteur MIDI puis durée en temps, deux par deux. Airs du domaine public, en do majeur. */
        private fun demo(id: String, titre: String, bpm: Int, vararg partition: Double): Demo {
            val temps = 60000.0 / bpm
            val notes = ArrayList<NoteMidi>()
            var t = 0.0
            for (i in partition.indices step 2) {
                val duree = partition[i + 1] * temps
                notes.add(NoteMidi(t.toLong(), (duree * 0.9).toInt(), partition[i].toInt()))
                t += duree
            }
            return Demo(id, titre, notes)
        }

        private val DEMOS = listOf(
            demo(
                "ode", "Ode à la joie", 132,
                64.0, 1.0, 64.0, 1.0, 65.0, 1.0, 67.0, 1.0, 67.0, 1.0, 65.0, 1.0, 64.0, 1.0, 62.0, 1.0,
                60.0, 1.0, 60.0, 1.0, 62.0, 1.0, 64.0, 1.0, 64.0, 1.5, 62.0, 0.5, 62.0, 2.0,
                64.0, 1.0, 64.0, 1.0, 65.0, 1.0, 67.0, 1.0, 67.0, 1.0, 65.0, 1.0, 64.0, 1.0, 62.0, 1.0,
                60.0, 1.0, 60.0, 1.0, 62.0, 1.0, 64.0, 1.0, 62.0, 1.5, 60.0, 0.5, 60.0, 2.0,
            ),
            demo(
                "lune", "Au clair de la lune", 112,
                72.0, 1.0, 72.0, 1.0, 72.0, 1.0, 74.0, 1.0, 76.0, 2.0, 74.0, 2.0,
                72.0, 1.0, 76.0, 1.0, 74.0, 1.0, 74.0, 1.0, 72.0, 4.0,
                72.0, 1.0, 72.0, 1.0, 72.0, 1.0, 74.0, 1.0, 76.0, 2.0, 74.0, 2.0,
                72.0, 1.0, 76.0, 1.0, 74.0, 1.0, 74.0, 1.0, 72.0, 4.0,
                74.0, 1.0, 74.0, 1.0, 74.0, 1.0, 74.0, 1.0, 69.0, 2.0, 69.0, 2.0,
                74.0, 1.0, 72.0, 1.0, 71.0, 1.0, 69.0, 1.0, 67.0, 4.0,
                72.0, 1.0, 72.0, 1.0, 72.0, 1.0, 74.0, 1.0, 76.0, 2.0, 74.0, 2.0,
                72.0, 1.0, 76.0, 1.0, 74.0, 1.0, 74.0, 1.0, 72.0, 4.0,
            ),
            demo(
                "jacques", "Frère Jacques", 120,
                72.0, 1.0, 74.0, 1.0, 76.0, 1.0, 72.0, 1.0, 72.0, 1.0, 74.0, 1.0, 76.0, 1.0, 72.0, 1.0,
                76.0, 1.0, 77.0, 1.0, 79.0, 2.0, 76.0, 1.0, 77.0, 1.0, 79.0, 2.0,
                79.0, 0.5, 81.0, 0.5, 79.0, 0.5, 77.0, 0.5, 76.0, 1.0, 72.0, 1.0,
                79.0, 0.5, 81.0, 0.5, 79.0, 0.5, 77.0, 0.5, 76.0, 1.0, 72.0, 1.0,
                72.0, 1.0, 67.0, 1.0, 72.0, 2.0, 72.0, 1.0, 67.0, 1.0, 72.0, 2.0,
            ),
        )
    }
}

/** InputStream.readNBytes n'existe qu'à partir d'Android 13. */
fun java.io.InputStream.lireAuPlus(max: Int): ByteArray {
    val sortie = java.io.ByteArrayOutputStream()
    val tampon = ByteArray(16 * 1024)
    while (sortie.size() < max) {
        val lu = read(tampon, 0, minOf(tampon.size, max - sortie.size()))
        if (lu < 0) break
        sortie.write(tampon, 0, lu)
    }
    return sortie.toByteArray()
}
