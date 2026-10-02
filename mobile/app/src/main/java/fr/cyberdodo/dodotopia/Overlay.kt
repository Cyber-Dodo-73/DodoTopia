package fr.cyberdodo.dodotopia

import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.Context
import android.graphics.PixelFormat
import android.graphics.PointF
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.SeekBar
import android.widget.TextView
import kotlin.math.hypot
import kotlin.math.min

/**
 * Tout ce que DodoTopia affiche par-dessus le jeu à l'étape 1 : la bulle, le panneau de test,
 * le viseur et sa barre. Ce sont des fenêtres TYPE_ACCESSIBILITY_OVERLAY, que seul le
 * WindowManager du service d'accessibilité a le droit de créer.
 *
 * À savoir pour les mesures : un geste envoyé par le service atterrit sur la fenêtre qui se trouve
 * à cet endroit, les nôtres comprises. D'où le panneau replié pendant le métronome et
 * l'avertissement quand la bulle recouvre un repère.
 */
class Overlay(private val service: DodoAccessibilityService) {

    private val contexte: Context = ContextThemeWrapper(service, R.style.Theme_DodoOverlay)
    private val fenetres = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val gonfleur = LayoutInflater.from(contexte)
    private val prefs = service.getSharedPreferences("etape1", Context.MODE_PRIVATE)
    private val principal = Handler(Looper.getMainLooper())
    private val dp = service.resources.displayMetrics.density

    private val reperes = mutableListOf<PointF>()
    private var resume = ""

    private var bulle: View? = null
    private var bulleParams: WindowManager.LayoutParams? = null
    private var panneau: View? = null
    private var viseur: View? = null
    private var barre: View? = null
    private var calque: ReperesView? = null

    init {
        chargerReperes()
    }

    // ------------------------------------------------------------------ fenêtres

    private fun params(largeur: Int, hauteur: Int, drapeaux: Int = 0): WindowManager.LayoutParams =
        WindowManager.LayoutParams(
            largeur, hauteur,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            // NO_LIMITS + IN_SCREEN : x et y comptent depuis le coin de l'écran, et le viseur
            // peut dépasser du bord pour viser une touche collée au bord.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or drapeaux,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }

    private fun retirer(vue: View?) {
        if (vue == null) return
        try {
            fenetres.removeView(vue)
        } catch (e: IllegalArgumentException) {
            // Déjà retirée (service coupé pendant une animation) : rien à faire.
        }
    }

    /** Déplace une fenêtre au doigt. Sans glissement, c'est un clic. */
    private inner class Glisser(
        private val p: WindowManager.LayoutParams,
        private val seuil: Int,
        private val surClic: (() -> Unit)?,
        private val surLacher: (() -> Unit)?,
    ) : View.OnTouchListener {
        private var x0 = 0f
        private var y0 = 0f
        private var px = 0
        private var py = 0
        private var glisse = false

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouch(v: View, ev: MotionEvent): Boolean {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    x0 = ev.rawX; y0 = ev.rawY; px = p.x; py = p.y; glisse = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = ev.rawX - x0
                    val dy = ev.rawY - y0
                    if (!glisse && hypot(dx, dy) > seuil) glisse = true
                    if (glisse && v.isAttachedToWindow) {
                        p.x = px + dx.toInt(); p.y = py + dy.toInt()
                        fenetres.updateViewLayout(v, p)
                    }
                }
                MotionEvent.ACTION_UP -> if (glisse) surLacher?.invoke() else surClic?.invoke()
                MotionEvent.ACTION_CANCEL -> if (glisse) surLacher?.invoke()
            }
            return true
        }
    }

    fun fermerTout() {
        principal.removeCallbacksAndMessages(null)
        fermerViseur()
        fermerPanneau()
        retirer(bulle)
        bulle = null
    }

    /** Les positions n'ont plus de sens après une rotation : on replie tout et on range la bulle. */
    fun surRotation() {
        fermerViseur()
        fermerPanneau()
        // Les repères de l'autre orientation tomberaient à côté, voire hors écran.
        reperes.clear()
        chargerReperes()
        principal.post { rangerBulle(anime = false) }
    }

    // ------------------------------------------------------------------ bulle

    fun montrerBulle() {
        if (bulle != null) return
        val vue = gonfleur.inflate(R.layout.overlay_bulle, null)
        val taille = (TAILLE_BULLE_DP * dp).toInt()
        val ecran = tailleEcran(service)
        val p = params(taille, taille).apply { x = ecran.x - taille; y = ecran.y / 3 }
        vue.setOnTouchListener(
            Glisser(p, ViewConfiguration.get(contexte).scaledTouchSlop, ::clicBulle) { rangerBulle(anime = true) }
        )
        fenetres.addView(vue, p)
        bulle = vue
        bulleParams = p
    }

    private fun clicBulle() {
        when {
            service.metronome.enCours -> arreterMesure()
            viseur != null -> fermerViseur().also { ouvrirPanneau() }
            panneau != null -> fermerPanneau()
            else -> ouvrirPanneau()
        }
    }

    /** Colle la bulle au bord gauche ou droit le plus proche, sans la laisser sortir en hauteur. */
    private fun rangerBulle(anime: Boolean) {
        val vue = bulle ?: return
        val p = bulleParams ?: return
        val ecran = tailleEcran(service)
        val taille = p.width
        val cible = if (p.x + taille / 2 < ecran.x / 2) 0 else ecran.x - taille
        p.y = p.y.coerceIn(0, ecran.y - taille)
        if (!anime) {
            p.x = cible
            if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            return
        }
        ValueAnimator.ofInt(p.x, cible).apply {
            duration = 180
            addUpdateListener {
                p.x = it.animatedValue as Int
                if (vue.isAttachedToWindow) fenetres.updateViewLayout(vue, p)
            }
            start()
        }
    }

    /** Pendant une mesure, la bulle devient un bouton Stop rouge. */
    private fun bulleEnStop(stop: Boolean) {
        val vue = bulle ?: return
        vue.setBackgroundResource(if (stop) R.drawable.bulle_fond_stop else R.drawable.bulle_fond)
        vue.findViewById<View>(R.id.imgBulle).visibility = if (stop) View.INVISIBLE else View.VISIBLE
        vue.findViewById<View>(R.id.carreStop).visibility = if (stop) View.VISIBLE else View.GONE
    }

    // ------------------------------------------------------------------ panneau

    private fun ouvrirPanneau() {
        if (panneau != null || bulle == null) return
        val vue = gonfleur.inflate(R.layout.overlay_panneau, null)

        vue.findViewById<Button>(R.id.btnFermer).setOnClickListener { fermerPanneau() }
        vue.findViewById<Button>(R.id.btnPlacer).setOnClickListener { ouvrirViseur() }
        vue.findViewById<Button>(R.id.btnEffacerReperes).setOnClickListener {
            reperes.clear()
            sauverReperes()
            majReperes(vue)
        }
        majReperes(vue)

        curseur(vue, R.id.seekBpm, R.id.txtBpm, "bpm", 120) { "Tempo : $it bpm" }
        curseur(vue, R.id.seekAppuis, R.id.txtAppuis, "appuis", 16) { "Nombre d'appuis : $it" }
        curseur(vue, R.id.seekDuree, R.id.txtDuree, "duree", 4) { "Durée d'un appui : ${it * 10} ms" }
        vue.findViewById<CheckBox>(R.id.chkAccord).apply {
            isChecked = prefs.getBoolean("accord", false)
            setOnCheckedChangeListener { _, coche -> prefs.edit().putBoolean("accord", coche).apply() }
        }

        vue.findViewById<Button>(R.id.btnLancer).setOnClickListener { lancerMesure() }
        vue.findViewById<Button>(R.id.btnCaptureService).setOnClickListener { capturer() }
        vue.findViewById<TextView>(R.id.txtResume).apply {
            text = resume
            visibility = if (resume.isEmpty()) View.GONE else View.VISIBLE
        }

        // Le panneau prend la hauteur de son contenu, plafonnée à l'écran : au-delà, il défile.
        val ecran = tailleEcran(service)
        val marge = (24 * dp).toInt()
        val largeur = min(((if (ecran.x > ecran.y) 620 else 360) * dp).toInt(), ecran.x - marge)
        vue.measure(
            View.MeasureSpec.makeMeasureSpec(largeur, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(ecran.y - marge, View.MeasureSpec.AT_MOST)
        )
        val p = params(largeur, vue.measuredHeight).apply {
            x = (ecran.x - largeur) / 2
            y = (ecran.y - vue.measuredHeight) / 2
        }
        fenetres.addView(vue, p)
        panneau = vue
    }

    private fun fermerPanneau() {
        retirer(panneau)
        panneau = null
    }

    private fun majReperes(vue: View) {
        vue.findViewById<TextView>(R.id.txtReperes).text = when (reperes.size) {
            0 -> "Aucun repère : place-en un sur chaque touche."
            1 -> "1 repère placé"
            else -> "${reperes.size} repères placés"
        }
    }

    /** Lie un curseur à son libellé et à sa préférence. */
    private fun curseur(vue: View, idCurseur: Int, idTexte: Int, cle: String, defaut: Int, libelle: (Int) -> String) {
        val texte = vue.findViewById<TextView>(idTexte)
        vue.findViewById<SeekBar>(idCurseur).apply {
            progress = prefs.getInt(cle, defaut)
            texte.text = libelle(progress)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar, valeur: Int, parUtilisateur: Boolean) {
                    texte.text = libelle(valeur)
                }

                override fun onStartTrackingTouch(s: SeekBar) = Unit

                override fun onStopTrackingTouch(s: SeekBar) {
                    prefs.edit().putInt(cle, s.progress).apply()
                }
            })
        }
    }

    private fun afficherResume(texte: String) {
        resume = texte
        val vue = panneau
        if (vue == null) {
            ouvrirPanneau()
        } else {
            // Le panneau ouvert a une hauteur figée : on le rouvre pour qu'il s'ajuste au nouveau texte.
            fermerPanneau()
            ouvrirPanneau()
        }
    }

    // ------------------------------------------------------------------ métronome et capture

    private fun lancerMesure() {
        if (reperes.isEmpty()) {
            afficherResume("Place d'abord un repère sur une touche de l'instrument.")
            return
        }
        val bpm = prefs.getInt("bpm", 120)
        val intervalle = 60000L / bpm
        // Un geste envoyé pendant qu'un autre est en cours annule le premier :
        // l'appui doit finir avant le suivant, avec un peu de marge.
        val duree = min(prefs.getInt("duree", 4) * 10L, intervalle - 20)
        val reglages = Reglages(
            bpm = bpm,
            appuis = prefs.getInt("appuis", 16),
            accord = prefs.getBoolean("accord", false),
            dureeMs = duree,
            reperes = reperes.map { PointF(it.x, it.y) },
        )
        val ecran = tailleEcran(service)
        SpikeLog.log(
            "Départ métronome · écran ${ecran.x}×${ecran.y} · repères " +
                reperes.joinToString(" ") { "(${it.x.toInt()},${it.y.toInt()})" } + alerteBulle()
        )
        fermerPanneau()
        bulleEnStop(true)
        service.metronome.lancer(reglages, ::finMesure)
    }

    fun arreterMesure() {
        service.metronome.arreter(::finMesure)
    }

    private fun finMesure(texte: String) {
        if (bulle == null) return
        bulleEnStop(false)
        Resultats.metronome.value = texte
        afficherResume(texte + alerteBulle())
    }

    /** La bulle avale les appuis qui tombent dessus : on le signale plutôt que de fausser la mesure en silence. */
    private fun alerteBulle(): String {
        val p = bulleParams ?: return ""
        val dessous = reperes.indexOfFirst {
            it.x >= p.x && it.x <= p.x + p.width && it.y >= p.y && it.y <= p.y + p.height
        }
        return if (dessous < 0) "" else "\nAttention : la bulle recouvre le repère ${dessous + 1}, déplace-la."
    }

    private fun capturer() {
        fermerPanneau()
        // Le temps que le panneau disparaisse de l'écran, sinon c'est lui qu'on photographie.
        principal.postDelayed({ service.capturer { texte -> if (bulle != null) afficherResume(texte) } }, 400)
    }

    // ------------------------------------------------------------------ viseur

    private fun ouvrirViseur() {
        fermerPanneau()
        if (viseur != null) return
        val ecran = tailleEcran(service)

        val fond = ReperesView(contexte, reperes)
        fenetres.addView(
            fond,
            params(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            )
        )
        calque = fond

        val cible = ViseurView(contexte)
        val taille = (TAILLE_VISEUR_DP * dp).toInt()
        val p = params(taille, taille).apply { x = (ecran.x - taille) / 2; y = (ecran.y - taille) / 2 }
        // Seuil nul : le viseur suit le doigt dès le premier pixel, pour viser fin.
        cible.setOnTouchListener(Glisser(p, 0, null, null))
        fenetres.addView(cible, p)
        viseur = cible

        val commandes = gonfleur.inflate(R.layout.overlay_barre_viseur, null)
        val compte = commandes.findViewById<TextView>(R.id.txtCompte)
        fun majCompte() {
            compte.text = "Repères : ${reperes.size}"
            fond.invalidate()
        }
        commandes.findViewById<Button>(R.id.btnValider).setOnClickListener {
            // Position réelle à l'écran, pas celle qu'on a demandée : c'est elle que dispatchGesture attend.
            val coin = IntArray(2)
            cible.getLocationOnScreen(coin)
            val point = PointF(coin[0] + cible.width / 2f, coin[1] + cible.height / 2f)
            reperes.add(point)
            sauverReperes()
            SpikeLog.log("Repère ${reperes.size} : (${point.x.toInt()}, ${point.y.toInt()})")
            majCompte()
        }
        commandes.findViewById<Button>(R.id.btnRetirer).setOnClickListener {
            if (reperes.isNotEmpty()) {
                reperes.removeAt(reperes.size - 1)
                sauverReperes()
                majCompte()
            }
        }
        commandes.findViewById<Button>(R.id.btnTerminer).setOnClickListener {
            fermerViseur()
            ouvrirPanneau()
        }
        majCompte()
        // En haut au centre : les touches de l'instrument sont en bas de l'écran.
        // Largeur mesurée à la main : une fenêtre WRAP_CONTENT est d'abord bridée à 320 dp par Android,
        // ce qui tronquait le dernier bouton.
        commandes.measure(
            View.MeasureSpec.makeMeasureSpec(ecran.x - (16 * dp).toInt(), View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val q = params(commandes.measuredWidth, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = (12 * dp).toInt()
        }
        fenetres.addView(commandes, q)
        barre = commandes
    }

    private fun fermerViseur() {
        retirer(viseur); viseur = null
        retirer(barre); barre = null
        retirer(calque); calque = null
    }

    // ------------------------------------------------------------------ repères enregistrés

    private fun sauverReperes() {
        val ecran = tailleEcran(service)
        prefs.edit()
            .putString("reperes", reperes.joinToString(";") { "${it.x},${it.y}" })
            .putString("reperes_ecran", "${ecran.x}x${ecran.y}")
            .apply()
    }

    private fun chargerReperes() {
        // Des repères placés dans une autre orientation viseraient à côté : on repart de zéro.
        val ecran = tailleEcran(service)
        if (prefs.getString("reperes_ecran", null) != "${ecran.x}x${ecran.y}") return
        for (morceau in prefs.getString("reperes", "").orEmpty().split(';')) {
            val xy = morceau.split(',')
            val x = xy.getOrNull(0)?.toFloatOrNull() ?: continue
            val y = xy.getOrNull(1)?.toFloatOrNull() ?: continue
            reperes.add(PointF(x, y))
        }
    }

    companion object {
        private const val TAILLE_BULLE_DP = 56
        private const val TAILLE_VISEUR_DP = 96
    }
}
