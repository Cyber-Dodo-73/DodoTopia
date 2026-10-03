package fr.cyberdodo.dodotopia

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.lifecycle.MutableLiveData
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/** Une version publiée de l'appli, telle que l'annonce `GET /api/mobile/latest`. */
class VersionPubliee(val version: String, val adresse: String, val sha256: String, val taille: Long, val notes: String)

/** Comparaison de numéros de version « 0.6.0 », sans rien d'Android : testable hors appareil. */
object Versions {
    /** Les nombres du numéro, dans l'ordre ; ce qui suit un tiret ou un plus (« -beta », « +build ») est ignoré. */
    fun nombres(version: String): List<Int>? {
        val coeur = version.trim().removePrefix("v").substringBefore('-').substringBefore('+')
        if (coeur.isEmpty()) return null
        val nombres = coeur.split('.').map { it.toIntOrNull() ?: return null }
        return nombres.takeIf { n -> n.all { it >= 0 } }
    }

    /** Vrai si [candidate] est strictement plus récente que [actuelle]. Un numéro illisible n'est jamais plus récent. */
    fun plusRecente(candidate: String, actuelle: String): Boolean {
        val a = nombres(candidate) ?: return false
        val b = nombres(actuelle) ?: return false
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }
}

/**
 * Mise à jour de l'appli : le serveur annonce la dernière version, l'APK est téléchargé dans le dossier privé
 * de l'appli, son sha256 est vérifié, puis l'installateur d'Android prend le relais (il redemande l'accord
 * du joueur et refuse un APK signé par une autre clé que celle de l'appli installée).
 *
 * L'installation depuis l'appli demande la permission REQUEST_INSTALL_PACKAGES dans le manifeste. Elle n'y
 * est plus depuis la 0.7.2 (Play Protect) : [installer] et l'interface ouvrent le téléchargement de l'APK
 * dans le navigateur, et c'est Android qui propose de l'installer par-dessus l'appli.
 */
object MiseAJour {

    class Etat(
        /** La version à installer, ou null si l'appli est à jour (ou pas encore vérifiée). */
        val version: VersionPubliee? = null,
        /** Téléchargement en cours : 0 à 100. */
        val progression: Int? = null,
        /** L'APK vérifié, prêt à installer. */
        val fichier: File? = null,
        val erreur: String? = null,
    )

    /** Observé par l'interface. */
    val etat = MutableLiveData(Etat())

    private const val TAILLE_MAX = 300L * 1024 * 1024
    private val SHA = Regex("^[0-9a-f]{64}$")

    @Volatile
    private var occupe = false

    private fun dossier(context: Context) = File(context.filesDir, "maj")

    /** Interroge le serveur sans bloquer ; le résultat arrive dans [etat]. Une panne de réseau ne s'affiche pas. */
    fun verifier(context: Context) {
        val app = context.applicationContext
        if (occupe) return
        occupe = true
        Serveur.fil.execute {
            val trouvee = try {
                derniere(app)
            } catch (e: ErreurEnLigne) {
                SpikeLog.log("Mise à jour : vérification impossible (${e.message})")
                occupe = false
                return@execute
            }
            occupe = false
            if (trouvee == null) {
                dossier(app).deleteRecursively()
                etat.postValue(Etat())
            } else {
                val pret = fichier(app, trouvee).takeIf { it.isFile && sha256(it) == trouvee.sha256 }
                etat.postValue(Etat(trouvee, fichier = pret))
            }
        }
    }

    /**
     * La dernière version publiée si elle est plus récente que celle-ci, sinon null. Bloquant.
     * 404 « no_release » : rien n'est publié, l'appli est à jour.
     */
    @Throws(ErreurEnLigne::class)
    fun derniere(context: Context): VersionPubliee? {
        val actuelle = BuildConfig.VERSION_NAME
        val r = try {
            Serveur.lire(context, "/api/mobile/latest?current=" + Uri.encode(actuelle))
        } catch (e: ErreurEnLigne) {
            if (e.code == 404) return null
            throw e
        }
        val v = VersionPubliee(
            r.optString("version"), r.optString("url"), r.optString("sha256").lowercase(),
            r.optLong("size"), r.optString("notes"),
        )
        if (!Versions.plusRecente(v.version, actuelle)) return null
        // Une annonce incomplète ou qui pointe ailleurs que sur le serveur de l'appli n'est pas suivie.
        val hote = Uri.parse(Serveur.adresse(context)).host
        val cible = Uri.parse(v.adresse)
        if (!SHA.matches(v.sha256) || cible.host == null || cible.host != hote || v.taille <= 0 || v.taille > TAILLE_MAX) {
            SpikeLog.log("Mise à jour : annonce refusée (${v.version}, ${v.adresse})")
            return null
        }
        return v
    }

    private fun fichier(context: Context, v: VersionPubliee) =
        File(dossier(context), "DodoTopia-" + v.version.filter { it.isLetterOrDigit() || it == '.' || it == '-' } + ".apk")

    /** Télécharge l'APK de [v] sans bloquer ; l'avancement puis le fichier vérifié arrivent dans [etat]. */
    fun telecharger(context: Context, v: VersionPubliee) {
        val app = context.applicationContext
        if (occupe) return
        occupe = true
        etat.value = Etat(v, progression = 0)
        Serveur.fil.execute {
            val resultat = try {
                Etat(v, fichier = recuperer(app, v) { etat.postValue(Etat(v, progression = it)) })
            } catch (e: ErreurEnLigne) {
                Etat(v, erreur = e.message)
            }
            occupe = false
            etat.postValue(resultat)
        }
    }

    /** Télécharge et vérifie l'APK. Bloquant. Un fichier dont l'empreinte ne correspond pas est supprimé. */
    @Throws(ErreurEnLigne::class)
    fun recuperer(context: Context, v: VersionPubliee, avancement: (Int) -> Unit): File {
        val cible = fichier(context, v)
        if (cible.isFile && sha256(cible) == v.sha256) return cible
        val partiel = File(cible.path + ".part")
        try {
            dossier(context).deleteRecursively()
            dossier(context).mkdirs()
            val requete = Request.Builder().url(v.adresse).header("User-Agent", Serveur.agent).get().build()
            Serveur.http.newCall(requete).execute().use { r ->
                if (!r.isSuccessful) throw ErreurEnLigne(context.getString(R.string.erreur_serveur, r.code), r.code)
                val empreinte = MessageDigest.getInstance("SHA-256")
                var recu = 0L
                var dernier = -1
                r.body!!.byteStream().use { flux ->
                    partiel.outputStream().use { sortie ->
                        val tampon = ByteArray(64 * 1024)
                        while (true) {
                            val lu = flux.read(tampon)
                            if (lu < 0) break
                            recu += lu
                            if (recu > v.taille) throw ErreurEnLigne(context.getString(R.string.maj_fichier_refuse))
                            empreinte.update(tampon, 0, lu)
                            sortie.write(tampon, 0, lu)
                            val pourcent = (100 * recu / v.taille).toInt()
                            if (pourcent != dernier) {
                                dernier = pourcent
                                avancement(pourcent)
                            }
                        }
                    }
                }
                val obtenu = empreinte.digest().joinToString("") { "%02x".format(it) }
                if (recu != v.taille || obtenu != v.sha256) {
                    SpikeLog.log("Mise à jour : fichier refusé ($recu octets, sha256 $obtenu)")
                    throw ErreurEnLigne(context.getString(R.string.maj_fichier_refuse))
                }
            }
            if (!partiel.renameTo(cible)) throw IOException("renommage impossible")
            return cible
        } catch (e: IOException) {
            SpikeLog.log("Mise à jour : ${e.javaClass.simpleName} ${e.message}")
            throw ErreurEnLigne(context.getString(R.string.erreur_reseau))
        } finally {
            partiel.delete()
        }
    }

    fun sha256(fichier: File): String {
        val empreinte = MessageDigest.getInstance("SHA-256")
        fichier.inputStream().use { flux ->
            val tampon = ByteArray(64 * 1024)
            while (true) {
                val lu = flux.read(tampon)
                if (lu < 0) break
                empreinte.update(tampon, 0, lu)
            }
        }
        return empreinte.digest().joinToString("") { "%02x".format(it) }
    }

    /** Vrai si le manifeste déclare REQUEST_INSTALL_PACKAGES : sans elle, Android ignore la demande d'installation. */
    fun peutInstaller(context: Context): Boolean = try {
        @Suppress("DEPRECATION")
        val infos = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        infos.requestedPermissions?.contains("android.permission.REQUEST_INSTALL_PACKAGES") == true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    /**
     * Lance l'installation de l'APK vérifié : Android affiche sa propre confirmation (et, la première fois,
     * l'autorisation d'installer depuis DodoTopia). Sans la permission au manifeste, ou sans installateur,
     * ouvre le téléchargement dans le navigateur. Rend vrai si l'installateur a été lancé.
     */
    fun installer(context: Context, v: VersionPubliee, fichier: File): Boolean {
        if (peutInstaller(context) && fichier.isFile) {
            try {
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", fichier)
                context.startActivity(
                    Intent(Intent.ACTION_VIEW)
                        .setDataAndType(uri, "application/vnd.android.package-archive")
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                )
                return true
            } catch (e: RuntimeException) {
                SpikeLog.log("Mise à jour : installateur introuvable (${e.javaClass.simpleName})")
            }
        }
        Connexion.ouvrir(context, v.adresse)
        return false
    }
}
