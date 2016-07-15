# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""

Provides a set of utility functions to deal with dust extinction.

*License*:
    Copyright (c) 2016, SDSS-IV/MaNGA Pipeline Group
        Licensed under BSD 3-clause license - see LICENSE.rst

*Source location*:
    $MANGADAP_DIR/python/mangadap/util/extinction.py

*Imports and python version compliance*:
    ::

        from __future__ import division
        from __future__ import print_function
        from __future__ import absolute_import
        from __future__ import unicode_literals

        import sys
        if sys.version > '3':
            long = int

        import numpy
        from scipy import linalg

*Class usage examples*:
    Add examples

*Revision history*:
    | **02 Jun 2016**: Original implementation by K. Westfall (KBW).
        Drawn from dust.py in David Wilkinson's FIREFLY code, and the
        dereddening functions in IDLUTILS.
    | **14 Jul 2016**: (KBW) Added :func:`apply_reddening`

"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from __future__ import unicode_literals

import sys
import warnings
if sys.version > '3':
    long = int

import numpy
from numpy.polynomial.polynomial import polyval
import scipy.interpolate

from ..mangafits import MaNGAFits

__author__ = 'Kyle Westfall'

def default_calzetti_rv():
    return 4.05

def reddening_vector_calzetti(wave, ebv, rv=None):
    r"""
    Return the Calzetti et al. (2000) reddening vector.

    Args:
        wave (array-like): Wavelengths at which to calculate the
            reddening vector curve in angstroms.
        ebv (float): E(B-V) reddening used to normalize the curve.
        rv (float): (**Optional**) Ratio of V-band extinction to the B-V
            reddening:

            .. math:: 

                R_V = \frac{A_V}{E(B-V)}

            Default is 4.05.  Typical value for the diffuse ISM of the
            Milky Way is 3.1.

    Returns:
        numpy.ma.MaskedArray: One-dimensional masked array with the
        reddening vector that can be used deredden a spectrum by
        calculating:

        .. math::

            F(\lambda) = a(\lambda) f(\lambda)

        where :math:`a` is the vector returned by this function,
        :math:`f` is the observed flux, and :math:`F` is the dereddened
        flux.
    """
    # Check shapes
    _wave = numpy.atleast_1d(wave)
    if len(_wave.shape) != 1:
        raise ValueError('Must only provide a single wavlength vector.')
    if not isinstance(ebv, float):
        raise TypeError('Input reddening value must be a single float.')

    # Wavenumber in 1/micron
    k = 1e4/_wave

    _rv = default_calzetti_rv() if rv is None else rv

    # Select valid wavelength ranges
    w1 = (_wave > 6300.) & (_wave < 22000.)
    w2 = (_wave > 912.) & (_wave <= 6300.)
    if numpy.sum(w1) + numpy.sum(w2) != _wave.size:
        warnings.warn('Invalid wavelength range in input vector.  Invalid regions will be masked.')

    # Extinction curve
    ext = numpy.ma.zeros(_wave.size, dtype=numpy.float)
    ext[~w1 & ~w2] = numpy.ma.masked
    ext[w1] = 2.659*(-1.857 + 1.040*k[w1]) + _rv
    ext[w2] = 2.659*(polyval(k[w2], [-2.156, 1.509, -0.198, 0.011])) + _rv

    # Return dereddening vector
    return numpy.ma.power(10., 0.4*ext*ebv)


def default_ccm_rv():
    return 3.1

def reddening_vector_ccm(wave, ebv, rv=None, original=False):
    r"""

    Return the reddening vector based on Cardelli, Clayton, and Mathis
    (1989 ApJ.  345, 245), including the update for the near-UV given by
    O'Donnell (1994, ApJ, 422, 158).   Parameterization is valid from
    the IR to the far-UV (3.5 microns to 0.1 microns). 

    Args:
        wave (array-like): Wavelengths at which to calculate the
            reddening vector in angstroms.
        ebv (float): E(B-V) reddening used to normalize the curve.
        rv (float): (**Optional**) Ratio of V-band extinction to the B-V
            reddening:

            .. math:: 

                R_V = \frac{A_V}{E(B-V)}

            Default is the typical value for the diffuse ISM of the
            Milky Way, :math:`R_V = 3.1`.
        original (bool): (**Optional**) Use the original coefficients
            from CCM89 instead of the updated coefficients from
            O'Donnell (1994).  Default is to use the updated
            coefficients.

    Returns:
        numpy.ma.MaskedArray: One-dimensional masked array with the
        reddening vector that can be used deredden a spectrum by
        calculating:

        .. math::

            F(\lambda) = a(\lambda) f(\lambda)

        where :math:`a` is the vector returned by this function,
        :math:`f` is the observed flux, and :math:`F` is the dereddened
        flux.
    """
    # Check shapes
    _wave = numpy.atleast_1d(wave)
    if len(_wave.shape) != 1:
        raise ValueError('Must only provide a single wavlength vector.')
    if not isinstance(ebv, float):
        raise TypeError('Input reddening value must be a single float.')

    # Wavenumber in 1/micron
    k = 1e4/_wave

    _rv = default_ccm_rv() if rv is None else rv

    a = numpy.zeros(k.size, dtype=numpy.float)
    b = numpy.zeros(k.size, dtype=numpy.float)

    # Compute the Infrared portion
    w1 = (k > 0.3) & (k < 1.1)
    a[w1] =  0.574 * numpy.power(k[w1],1.61)
    b[w1] = -0.527 * numpy.power(k[w1],1.61)

    # Compute the Optical/NIR portion
    if original:
        c1 = numpy.array([      1.,  0.17699, -0.50447, -0.02427,  0.72085,  0.01979, -0.77530,
                           0.32999 ])
        c2 = numpy.array([      0.,  1.41338,  2.28305,  1.07233, -5.38434, -0.62251,  5.30260,
                          -2.09002 ])
    else:
        c1 = numpy.array([     1., 0.104,   -0.609,    0.701,  1.137, -1.718,   -0.827,    1.647,
                           -0.505 ])
        c2 = numpy.array([     0., 1.952,    2.908,   -3.989, -7.985, 11.102,    5.491,  -10.805,
                            3.347 ])
    w1 = (k >= 1.1) & (k < 3.3)
    a[w1] = polyval(k[w1] - 1.82, c1)
    b[w1] = polyval(k[w1] - 1.82, c2)

    # Compute the mid-UV portion
    w1 = (k >= 3.3) & (k < 8.)

    w2 = w1 & (k > 5.9)
    fa = numpy.zeros(k.size, dtype=numpy.float)
    fb = numpy.zeros(k.size, dtype=numpy.float)
    fa[w2] = -0.04473 * numpy.square(k[w2]-5.9) - 0.009779 * numpy.power(k[w2]-5.9,3)
    fb[w2] =   0.2130 * numpy.square(k[w2]-5.9) +   0.1207 * numpy.power(k[w2]-5.9,3)

    a[w1] =  1.752 - 0.316*k[w1] - (0.104 / ( numpy.square(k[w1]-4.67) + 0.341 )) + fa[w1]
    b[w1] = -3.090 + 1.825*k[w1] + (1.206 / ( numpy.square(k[w1]-4.62) + 0.263 )) + fb[w1]

    # Compute the far-UV portion
    w1 = (k >= 8.) & (k <= 11.)
    a[w1] = polyval(k[w1]-8., [ -1.073, -0.628,  0.137, -0.070 ])
    b[w1] = polyval(k[w1]-8., [ 13.670,  4.257, -0.420,  0.374 ])

    ext = numpy.ma.MaskedArray(_rv*(a+b/_rv))
    ext[ (k<=0.3) | (k>11.) ] = numpy.ma.masked

    # Return dereddening vector
    return numpy.ma.power(10., 0.4*ext*ebv)


class FMExtinctionCoefficients:
    def __init__(self, k0, gamma, c1, c2, c3, c4):
        self.k0 = k0
        self.gamma = gamma
        self.c1 = c1
        self.c2 = c2
        self.c3 = c3
        self.c4 = c4

    @classmethod
    def from_Rv(cls, rv):
        c2 = -0.824 + 4.717/rv
        return cls(4.596, 0.99, 2.030 - 3.007*c2, c2, 3.23, 0.41)


class AvgLMCExtinctionCoefficients(FMExtinctionCoefficients):
    def __init__(self):
        FMExtinctionCoefficients.__init__(self, 4.626, 1.05, -2.16, 1.31, 1.92, 0.42)


class LMC2ExtinctionCoefficients(FMExtinctionCoefficients):
    def __init__(self):
        FMExtinctionCoefficients.__init__(self, 4.596, 0.91, -1.28, 1.11, 2.73, 0.64)


def default_fm_rv():
    return 3.1


def reddening_vector_fm(wave, ebv, rv=None, coeffs=None):
    r"""

    Return the reddening vector based on Fitzpatrick & Massa
    (Fitzpatrick, 1999, PASP, 111, 63; astro-ph/9809387 ).
    Parameterization is valid from the IR to the far-UV (3.5 microns to
    0.1 microns). UV extinction curve is extrapolated down to 912
    Angstroms.

    Args:
        wave (array-like): Wavelengths at which to calculate the
            reddening vector in angstroms.
        ebv (float): E(B-V) reddening used to normalize the curve.
        rv (float): (**Optional**) Ratio of V-band extinction to the B-V
            reddening:

            .. math:: 

                R_V = \frac{A_V}{E(B-V)}

            Default is the typical value for the diffuse ISM of the
            Milky Way, :math:`R_V = 3.1`.
        coeffs (:class:`FMExtinctionCoefficients`): (**Optional**)
            Object with the coefficients to use for the extinction
            curve.  Default is to use the :math:`R_V` dependent
            coefficients defined using the
            :func:`FMExtinctionCoefficients.from_Rv` class method.

    Returns:
        numpy.ma.MaskedArray: One-dimensional masked array with the
        reddening vector that can be used deredden a spectrum by
        calculating:

        .. math::

            F(\lambda) = a(\lambda) f(\lambda)

        where :math:`a` is the vector returned by this function,
        :math:`f` is the observed flux, and :math:`F` is the dereddened
        flux.
    """
    # Check shapes
    _wave = numpy.atleast_1d(wave)
    if len(_wave.shape) != 1:
        raise ValueError('Must only provide a single wavlength vector.')
    if not isinstance(ebv, float):
        raise TypeError('Input reddening value must be a single float.')

    # Check the provided coefficients
    if coeffs is not None and not isinstance(FMExtinctionCoefficients):
        raise TypeError('Coefficients must be provided by a FMExtinctionCoefficients object.')

    _rv = default_fm_rv() if rv is None else rv
    _coeffs = FMExtinctionCoefficients.from_Rv(_rv) if coeffs is None else coeffs

    # Wavenumber in 1/micron
    k = 1e4/_wave
    ext = numpy.ma.zeros(_wave.size, dtype=numpy.float)
    
    # UV portion
    w1 = k > 1e4/2700.
    splpts_uv_k = 1e4/numpy.array([2700.,2600.])
    uv_k = numpy.append(splpts_uv_k, k[w1]) if numpy.sum(w1) > 0 else splpts_uv_k

    uv_k2 = numpy.square(uv_k)
    uv_kclip = (uv_k-5.9).clip(0.,None)
    uv_ext = _coeffs.c1  + _coeffs.c2*uv_k \
             + _coeffs.c3*uv_k2/(numpy.square(uv_k2 - _coeffs.k0**2) + uv_k2*_coeffs.gamma**2) \
             + _coeffs.c4*(0.5392*numpy.square(uv_kclip)+0.05644*numpy.power(uv_kclip,3)) + _rv

    # Pull out spline points
    splpts_uv_ext, ext[w1] = uv_ext[:2], uv_ext[2:] 

    # Return if no optical/IR part
    if numpy.sum(~w1) == 0:
        return numpy.ma.power(10., 0.4*ext*ebv)

    # Optical/IR portion
    splpts_oi_k = numpy.append([0],10000.0/numpy.array([26500.0, 12200.0, 6000.0, 5470.0, 4670.0,
                                                        4110.0]))

    splpts_oi_ext = numpy.append( numpy.array([0.0,0.26469,0.82925])*_rv/3.1,
                                  numpy.array([ polyval(_rv, [-4.22809e-01, 1.00270,  2.13572e-04]),
                                                polyval(_rv, [-5.13540e-02, 1.00216, -7.35778e-05]),
                                                polyval(_rv, [ 7.00127e-01, 1.00184, -3.32598e-05]),
                                                polyval(_rv, [     1.19456, 1.01707, -5.46959e-03,
                                                               7.97809e-04, -4.45636e-05]) ]) )
    tck = scipy.interpolate.splrep(numpy.append(splpts_oi_k,splpts_uv_k),
                                   numpy.append(splpts_oi_ext,splpts_uv_ext), s=0)
    ext[~w1] = scipy.interpolate.splev(k[~w1], tck)

    return numpy.ma.power(10., 0.4*ext*ebv)


def reddening_vector(wave, ebv, form='ODonnell', rv=None, coeffs=None):
    if form == 'ODonnell':
        return reddening_vector_ccm(wave, ebv, rv=rv, original=False)

    if form == 'CCM':
        return reddening_vector_ccm(wave, ebv, rv=rv, original=True)

    if form == 'FM':
        return reddening_vector_fm(wave, ebv, rv=rv, coeffs=coeffs)
        
    if form == 'Calzetti':
        return reddening_vector_calzetti(wave, ebv, rv=rv)

    raise ValueError('Unrecognized form of the extinction law: {0}'.format(form))
        

def apply_reddening(flux, reddening_correction, dispaxis=2, deredden=True, ivar=None):
    """
    Apply the reddening.  Default operation is to **deredden** a
    spectrum.  Set deredden=False to **redden** a spectrum.

    The reddening vector is expected to be the multiplicative factor
    needed to **deredden** the spectrum.  I.e., the returned array
    when dereddening will be: dereddened_flux = flux *
    reddening_correction.

    Errors propagated if ivar provided.

    If ivar provided, returns flux and ivar arrays; if not, only flux
    array is returned.
    """

    # Check the input
    if len(reddening_correction.shape) != 1:
        raise ValueError('Input reddening correction must be a vector.')
    if ivar is not None and flux.shape != ivar.shape:
        raise ValueError('Flux and inverse variance arrays must have the same shape.')
    if len(flux.shape) == 1:
        if flux.size != reddening_correction.size:
            raise ValueError('Fluxe and reddening vector must have same number of wavelengths.')
        _flux = flux * reddening_correction if deredden else flux / reddening_correction
        if ivar is None:
            return _flux
        return _flux, ivar / numpy.square(reddening_correction) if deredden \
                        else ivar * numpy.square(reddening_correction)
    if dispaxis is None:
        raise ValueError('Must provide dispersion axis if flux array is multidimensional.')

    spatial_shape = MaNGAFits.get_spatial_shape(flux.shape, dispaxis)
    c = numpy.array([reddening_correction]*numpy.prod(spatial_shape)).reshape(*spatial_shape,-1)
    _flux = flux * c if deredden else flux / c
    if ivar is None:
        return _flux
    return _flux, ivar / numpy.square(c) if deredden else ivar * numpy.square(c)

