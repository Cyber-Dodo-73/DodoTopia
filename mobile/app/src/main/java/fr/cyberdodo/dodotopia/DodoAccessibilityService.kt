package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.Build
import android.os.SystemClock
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import androidx.lifecycle.MutableLiveData

/**
 * Le cœur de l'appli côté système : envoie les gestes, porte la bulle (fenêtre d'accessibilité,
 * donc sans SYSTEM_ALERT_WINDOW), intercepte volume bas et sait faire une capture de secours.
 * Activer le service ne suffit pas à faire apparaître la bulle : il faut aussi l'allumer dans l'appli,
 * et elle ne se montre que par-dessus Heartopia.
 */
class DodoAccessibilityService : AccessibilityService() {

    lateinit var lecteur: Lecteur
        private set
    lateinit var metronome: Metronome
        private set
    lateinit var traceur: Traceur
        private set
    lateinit var peintre: Peintre
        private set

    /** null avant Android 11 : la capture par le service n'existe pas. */
    var cuisine: Cuisine? = null
        private set
    private var overlay: Overlay? = null

    /** Vrai tant qu'Heartopia est la fenêtre au premier plan. */
    private var jeuDevant = false

    /** Après avoir avalé l'appui de volume bas, on avale aussi son relâchement, sinon le volume bouge. */
    private var avalerRelachement = false

    override fun onServiceConnected() {
        SpikeLog.init(this)
        lecteur = Lecteur(this)
        metronome = Metronome(this)
        traceur = Traceur(this)
        peintre = Peintre(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) cuisine = Cuisine(this)
        overlay = Overlay(this)
        instance = this
        actif.value = true
        // Dernier état connu (le service redémarre à chaque mise à jour, souvent pendant que le jeu est devant).
        jeuDevant = Preferences.prefs(this).getBoolean(JEU_DEVANT, true)
        try {
            appliquerBulle()
        } catch (e: RuntimeException) {
            // Une bulle qui ne s'affiche pas ne doit pas tuer le service : Android le laisserait « activé »
            // dans ses réglages mais mort, et l'appli resterait bloquée sur « à activer ».
            SpikeLog.log("Bulle impossible à la connexion du service : ${e.javaClass.simpleName} ${e.message.orEmpty()}")
        }
        val e = tailleEcran(this)
        SpikeLog.log(
            "Service d'accessibilité connecté · ${Build.MANUFACTURER} ${Build.MODEL} · " +
                "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · écran ${e.x}×${e.y}"
        )
    }

    /** Montre ou retire la bulle selon le choix fait dans l'appli (interrupteur « Bulle dans le jeu »). */
    fun appliquerBulle() {
        val o = overlay ?: return
        if (Preferences.bulleActive(this) && jeuDevant) o.montrerBulle() else o.fermerTout()
    }

    /** Départ synchronisé d'un salon. Faux si la bulle n'est pas prête à jouer (éteinte, occupée, clavier non calibré). */
    fun jouerSalon(titre: String, code: String, arrangement: Arrangement, delaiMs: Long): Boolean =
        overlay?.jouerSalon(titre, code, arrangement, delaiMs) ?: false

    fun arreterSalon() {
        overlay?.arreterSalon()
    }

    /**
     * Seul événement écouté : le changement de fenêtre au premier plan, dont on ne lit que le nom du paquet.
     * La bulle n'existe que par-dessus Heartopia ; quitter le jeu la retire et arrête ce qui jouait, pour
     * qu'aucun geste ne parte sur une autre appli.
     */
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val paquet = event.packageName?.toString() ?: return
        val classe = event.className?.toString().orEmpty()
        val devant = when {
            estLeJeu(paquet) -> true
            // Nos propres fenêtres par-dessus le jeu ne comptent pas ; l'écran de l'appli, si.
            paquet == packageName -> if (classe.endsWith("MainActivity")) false else return
            // Clavier, volet des notifications : le jeu est toujours dessous.
            paquet == "com.android.systemui" || classe.contains("SoftInputWindow") || paquet.contains("inputmethod") -> return
            else -> false
        }
        if (devant != jeuDevant) {
            jeuDevant = devant
            Preferences.prefs(this).edit().putBoolean(JEU_DEVANT, devant).apply()
            appliquerBulle()
        }
    }

    private fun estLeJeu(paquet: String): Boolean =
        paquet.startsWith(PREFIXE_JEU) || (BuildConfig.DEBUG && paquet == "com.android.settings")

    override fun onInterrupt() = Unit

    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) return false
        if (event.action == KeyEvent.ACTION_DOWN && (lecteur.enCours || metronome.enCours || peintre.enCours || cuisine?.enCours == true)) {
            SpikeLog.log("Volume bas : arrêt")
            overlay?.arretUrgence()
            avalerRelachement = true
            return true
        }
        if (event.action == KeyEvent.ACTION_UP && avalerRelachement) {
            avalerRelachement = false
            return true
        }
        // Quand rien ne joue, la touche garde son rôle normal.
        return false
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        overlay?.surRotation()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        fermer()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        fermer()
        super.onDestroy()
    }

    private fun fermer() {
        val o = overlay ?: return
        overlay = null
        instance = null
        o.fermerTout()
        lecteur.fermer()
        metronome.fermer()
        actif.value = false
        SpikeLog.log("Service d'accessibilité arrêté")
    }

    /**
     * Capture de secours par le service (Android 11+, 3 par seconde au mieux).
     * Mesure le temps de la capture seule, puis celui de la copie en mémoire lisible,
     * parce que la cuisine aurait besoin des deux.
     */
    fun capturer(surFin: (String) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            val texte = "Capture par le service : indisponible avant Android 11 (ici API ${Build.VERSION.SDK_INT})."
            SpikeLog.log(texte)
            surFin(texte)
            return
        }
        val debut = SystemClock.elapsedRealtime()
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(resultat: ScreenshotResult) {
                val capture = SystemClock.elapsedRealtime() - debut
                val tampon = resultat.hardwareBuffer
                val image = Bitmap.wrapHardwareBuffer(tampon, resultat.colorSpace)
                    ?.copy(Bitmap.Config.ARGB_8888, false)
                tampon.close()
                val texte = if (image == null) {
                    "Capture par le service : reçue en $capture ms mais illisible."
                } else {
                    val copie = SystemClock.elapsedRealtime() - debut - capture
                    val centre = luminosite(image.getPixel(image.width / 2, image.height / 2))
                    var somme = 0
                    for (i in 0 until GRILLE) for (j in 0 until GRILLE) {
                        somme += luminosite(
                            image.getPixel(image.width * (2 * i + 1) / (2 * GRILLE), image.height * (2 * j + 1) / (2 * GRILLE))
                        )
                    }
                    val moyenne = somme / (GRILLE * GRILLE)
                    val l = image.width
                    val h = image.height
                    image.recycle()
                    "Capture par le service : $capture ms (+ $copie ms de copie) · $l×$h · " +
                        "luminosité centre $centre, moyenne $moyenne" +
                        if (centre == 0 && moyenne == 0) " · NOIR : fenêtre protégée ?" else ""
                }
                SpikeLog.log(texte)
                surFin(texte)
            }

            override fun onFailure(code: Int) {
                val raison = when (code) {
                    ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR -> "erreur interne"
                    ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS -> "accès refusé au service"
                    ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> "captures trop rapprochées"
                    ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY -> "écran invalide"
                    else -> "code $code"
                }
                val texte = "Capture par le service : échec ($raison) après ${SystemClock.elapsedRealtime() - debut} ms."
                SpikeLog.log(texte)
                surFin(texte)
            }
        })
    }

    companion object {
        /** Vrai tant que le service est connecté : l'activité s'y abonne pour son état. */
        val actif = MutableLiveData(false)

        /**
         * Vrai si le service est coché dans les réglages d'accessibilité d'Android, qu'il soit connecté ou non.
         * Quand l'appli a été arrêtée de force (ou tuée par l'économie de batterie de certains téléphones),
         * Android peut le laisser coché sans le relancer : [actif] reste faux, et seul un arrêt puis une
         * réactivation du service dans les réglages le fait repartir.
         */
        fun activeDansAndroid(context: android.content.Context): Boolean {
            val liste = android.provider.Settings.Secure.getString(
                context.contentResolver, android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            val moi = android.content.ComponentName(context, DodoAccessibilityService::class.java)
            return liste.split(':').any { android.content.ComponentName.unflattenFromString(it) == moi }
        }

        /** Le service connecté, pour que l'activité lui demande de montrer ou retirer la bulle. */
        @Volatile
        var instance: DodoAccessibilityService? = null
            private set

        private const val GRILLE = 5

        /** Paquets d'Heartopia : « com.xd.xdtglobal.gp » sur le Play Store ; les versions de test visent aussi les Réglages. */
        private const val PREFIXE_JEU = "com.xd.xdt"
        private const val JEU_DEVANT = "jeu_devant"
    }
}
