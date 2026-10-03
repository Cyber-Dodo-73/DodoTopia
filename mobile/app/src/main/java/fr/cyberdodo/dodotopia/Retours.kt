package fr.cyberdodo.dodotopia

import android.app.Activity
import android.content.Context
import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.view.AccessibilityDelegateCompat
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat

/**
 * Message bref au bas de l'écran, à la place des toasts du système : aux couleurs de l'appli, en rouge
 * pour une erreur, lu par TalkBack (zone « live »), avec un petit retour haptique. Il cherche la vue
 * `R.id.annonce` de l'activité ; un écran qui n'en a pas retombe sur un toast.
 */
object Annonce {
    fun montrer(a: Activity, texte: CharSequence, erreur: Boolean = false) {
        val vue = a.findViewById<TextView>(R.id.annonce)
        if (vue == null) {
            Toast.makeText(a, texte, if (erreur) Toast.LENGTH_LONG else Toast.LENGTH_SHORT).show()
            return
        }
        vue.removeCallbacks(vue.tag as? Runnable)
        vue.animate().cancel()
        vue.text = texte
        vue.setBackgroundResource(if (erreur) R.drawable.annonce_erreur else R.drawable.annonce)
        vue.setCompoundDrawablesRelativeWithIntrinsicBounds(if (erreur) R.drawable.ic_alerte else R.drawable.ic_coche, 0, 0, 0)
        if (vue.visibility != View.VISIBLE) {
            vue.visibility = View.VISIBLE
            vue.alpha = 0f
            vue.translationY = 16 * a.resources.displayMetrics.density
        }
        vue.animate().alpha(1f).translationY(0f).setDuration(160).withEndAction(null).start()
        if (erreur) vue.vibrerErreur() else vue.vibrerOk()
        val cacher = Runnable {
            vue.animate().alpha(0f).setDuration(200).withEndAction { vue.visibility = View.GONE }.start()
        }
        vue.tag = cacher
        // Le temps de lire : une erreur reste plus longtemps, un long texte aussi.
        vue.postDelayed(cacher, (if (erreur) 4500L else 2600L) + texte.length * 25L)
    }

    fun montrer(a: Activity, texte: Int, erreur: Boolean = false) = montrer(a, a.getString(texte), erreur)
}

/** Retours haptiques : discrets, et muets si l'utilisateur a coupé les vibrations au toucher. */
fun View.tic() {
    performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
}

fun View.vibrerOk() {
    performHapticFeedback(if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.CONTEXT_CLICK)
}

fun View.vibrerErreur() {
    performHapticFeedback(if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS)
}

/**
 * Nos interrupteurs sont de simples vues habillées (`interrupteur.xml`, allumé = `isSelected`) :
 * on les présente aux lecteurs d'écran comme les interrupteurs qu'ils sont.
 */
fun View.commeInterrupteur() {
    ViewCompat.setAccessibilityDelegate(this, object : AccessibilityDelegateCompat() {
        override fun onInitializeAccessibilityNodeInfo(host: View, info: AccessibilityNodeInfoCompat) {
            super.onInitializeAccessibilityNodeInfo(host, info)
            info.className = "android.widget.Switch"
            info.isCheckable = true
            info.isChecked = host.isSelected
            info.isSelected = false
        }
    })
}

/** Thème clair, sombre, ou celui du téléphone (par défaut). Le choix se fait dans les réglages de l'appli. */
object Apparence {
    private const val CLE = "apparence"
    const val SYSTEME = "systeme"
    const val CLAIR = "clair"
    const val SOMBRE = "sombre"

    fun choix(context: Context): String = Preferences.prefs(context).getString(CLE, SYSTEME) ?: SYSTEME

    fun definir(context: Context, choix: String) {
        Preferences.prefs(context).edit().putString(CLE, choix).apply()
        appliquer(context)
    }

    /** À appeler avant `super.onCreate` de chaque activité : sans effet si le mode est déjà le bon. */
    fun appliquer(context: Context) {
        AppCompatDelegate.setDefaultNightMode(
            when (choix(context)) {
                CLAIR -> AppCompatDelegate.MODE_NIGHT_NO
                SOMBRE -> AppCompatDelegate.MODE_NIGHT_YES
                else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
        )
    }
}
