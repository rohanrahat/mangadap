# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""

Class that performs a number of assessments of a DRP file needed for
handling of the data by the DAP.  These assessments need only be done
once per DRP data file.

*License*:
    Copyright (c) 2015, SDSS-IV/MaNGA Pipeline Group
        Licensed under BSD 3-clause license - see LICENSE.rst

*Source location*:
    $MANGADAP_DIR/python/mangadap/proc/reductionassessments.py

*Imports and python version compliance*:
    ::

        from __future__ import division
        from __future__ import print_function
        from __future__ import absolute_import
        from __future__ import unicode_literals

        import sys
        import warnings
        if sys.version > '3':
            long = int
            try:
                from configparser import ConfigParser
            except ImportError:
                warnings.warn('Unable to import configparser!  Beware!')
            try:
                from configparser import ExtendedInterpolation
            except ImportError:
                warnings.warn('Unable to import ExtendedInterpolation!  Some configurations will fail!')
        else:
            try:
                from ConfigParser import ConfigParser
            except ImportError:
                warnings.warn('Unable to import ConfigParser!  Beware!')
            try:
                from ConfigParser import ExtendedInterpolation
            except ImportError:
                warnings.warn('Unable to import ExtendedInterpolation!  Some configurations will fail!')
        
        import glob
        import os.path
        from os import remove, environ
        from scipy import sparse
        from astropy.io import fits
        import astropy.constants
        import time
        import numpy

        from ..par.parset import ParSet
        from ..config.defaults import default_dap_source, default_dap_reference_path
        from ..config.defaults import default_dap_file_name
        from ..util.idlutils import airtovac
        from ..util.geometry import SemiMajorAxisCoo
        from ..util.fileio import init_record_array
        from ..drpfits import DRPFits
        from .util import _select_proc_method

.. warning::

    Because of the use of the ``ExtendedInterpolation`` in
    `configparser.ConfigParser`_,
    :func:`available_emission_bandpass_filter_databases`` is not python
    2 compiliant.
    
*Class usage examples*:

    .. todo::
        Add examples

*Revision history*:
    | **24 Mar 2016**: Implementation begun by K. Westfall (KBW)

.. _astropy.io.fits.hdu.hdulist.HDUList: http://docs.astropy.org/en/v1.0.2/io/fits/api/hdulists.html
.. _glob.glob: https://docs.python.org/3.4/library/glob.html
.. _configparser.ConfigParser: https://docs.python.org/3/library/configparser.html#configparser.ConfigParser


"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from __future__ import unicode_literals

import sys
import warnings
if sys.version > '3':
    long = int
    try:
        from configparser import ConfigParser
    except ImportError:
        warnings.warn('Unable to import configparser!  Beware!', ImportWarning)
    try:
        from configparser import ExtendedInterpolation
    except ImportError:
        warnings.warn('Unable to import ExtendedInterpolation!  Some configurations will fail!',
                      ImportWarning)
else:
    try:
        from ConfigParser import ConfigParser
    except ImportError:
        warnings.warn('Unable to import ConfigParser!  Beware!', ImportWarning)
    try:
        from ConfigParser import ExtendedInterpolation
    except ImportError:
        warnings.warn('Unable to import ExtendedInterpolation!  Some configurations will fail!', 
                      ImportWarning)

import glob
import os.path
from os import remove, environ
from scipy import sparse
from astropy.io import fits
import astropy.constants
import time
import numpy

from ..par.parset import ParSet
from ..config.defaults import default_dap_source, default_dap_reference_path
from ..config.defaults import default_dap_file_name
from ..util.covariance import Covariance
from ..util.idlutils import airtovac
from ..util.geometry import SemiMajorAxisCoo
from ..util.fileio import init_record_array, rec_to_fits_type, write_hdu
from ..drpfits import DRPFits
from .util import _select_proc_method

from matplotlib import pyplot

__author__ = 'Kyle B. Westfall'
# Add strict versioning
# from distutils.version import StrictVersion

class ReductionAssessmentDef(ParSet):
    """
    Class with parameters used to define how the reduction assessments
    are performed.  At the moment this is just a set of parameters that
    define how the S/N is calculated.

    See :class:`mangadap.par.parset.ParSet` for attributes.

    Args:
        key (str): Keyword to distinguish the assessment method.
        waverange (numpy.ndarray, list) : A two-element vector with the
            starting and ending wavelength (angstroms in VACUUM) within
            which to calculate the signal-to-noise
        covariance (str) : Type of covariance measurement to produce
    """
    def __init__(self, key, waverange, covariance):
        # Perform some checks of the input
        ar_like = [ numpy.ndarray, list ]
        #covar_opt = covariance_options()
        
        pars =   [ 'key', 'waverange', 'covariance' ]
        values = [   key,   waverange,   covariance ]
        #options = [ None,        None,    covar_opt ]
        dtypes = [   str,     ar_like,         bool ]

        #ParSet.__init__(self, pars, values=values, options=options, dtypes=dtypes)
        ParSet.__init__(self, pars, values=values, dtypes=dtypes)


def validate_reduction_assessment_config(cnfg):
    """ 
    Validate the `configparser.ConfigParser`_ object that is meant to
    define a reduction assessment method.

    Args:
        cnfg (`configparser.ConfigParser`_): Object meant to contain
            defining parameters of the reduction assessment method as
            needed by
            :class:`mangadap.proc.reductionassessments.ReductionAssessmentsDef`.

    Returns:
        bool: Booleans that specify how the reduction assessment should
        be constructed.  The flags specify to use (1) the wavelength
        range, (2) a bandpass filter parameter file, or (3) a file with
        a filter response function.

    Raises:
        KeyError: Raised if required keyword does not exist.
        ValueError: Raised if keys have unacceptable values.
        FileNotFoundError: Raised if a file is specified but could not
            be found.
    """
    # Check for required keywords
    if 'key' not in cnfg.options('default'):
        raise KeyError('Keyword \'key\' must be provided.')
    if 'wave_limits' not in cnfg.options('default') \
        and 'par_file' not in cnfg.options('default') \
        and 'response_function_file' not in cnfg.options('default'):
        raise KeyError('Method undefined.  Must provide \'wave_limits\' or \'par_file\' '
                       'or \'response_function_file\'.')

    def_range = ('wave_limits' in cnfg.options('default') \
                    and cnfg['default']['wave_limits'] is not None)

    def_par = ('par_file' in cnfg.options('default') and cnfg['default']['par_file'] is not None)

    def_response = ('response_function_file' in cnfg.options('default') \
                        and cnfg['default']['response_function_file'] is not None)

    if numpy.sum([ def_range, def_par, def_response] ) != 1:
        raise ValueError('Method undefined.  Must provide one and only one of \'wave1\' and '
                         '\'wave2\' or \'par_file\' or \'response_function_file\'.')

    if def_par and not os.path.isfile(cnfg['default']['par_file']):
        raise FileNotFoundError('par_file does not exist: {0}'.format(cnfg['default']['par_file']))
    if def_response and not os.path.isfile(cnfg['default']['response_function_file']):
        raise FileNotFoundError('response_function_file does not exist: {0}'.format(
                                cnfg['default']['response_function_file']))

    return def_range, def_par, def_response


def available_reduction_assessments(dapsrc=None):
    """
    Return the list of available reduction assessment methods.  The
    following methods are available with the DAP.

    +------------+---------------+---------+---------+
    |            |    Wavelength |    In   |         |
    |        Key |   Range (ang) | Vacuum? |   Covar |
    +============+===============+=========+=========+
    |      RFWHM | 5600.1-6750.0 |    True |   False |
    +------------+---------------+---------+---------+

    .. warning::

        Function is currently only valid for Python 3.2 or greater!

    Args:
        dapsrc (str): (**Optional**) Root path to the DAP source
            directory.  If not provided, the default is defined by
            :func:`mangadap.config.defaults.default_dap_source`.

    Returns:
        list: A list of
        :func:`mangadap.proc.reductionassessments.ReductionAssessmentDef`
        objects, each defining a separate assessment method.

    Raises:
        NotADirectoryError: Raised if the provided or default
            *dapsrc* is not a directory.
        OSError/IOError: Raised if no reduction assessment configuration
            files could be found.
        KeyError: Raised if the assessment method keywords are not all
            unique.
        NameError: Raised if either ConfigParser or
            ExtendedInterpolation are not correctly imported.  The
            latter is a *Python 3 only module*!

    .. todo::
        - Add backup function for Python 2.
        - Somehow add a python call that reads the databases and
          constructs the table for presentation in sphinx so that the
          text above doesn't have to be edited with changes in the
          available databases.
        
    """
    # Check the source directory exists
    dapsrc = default_dap_source() if dapsrc is None else str(dapsrc)
    if not os.path.isdir(dapsrc):
        raise NotADirectoryError('{0} does not exist!'.format(dapsrc))

    # Check the configuration files exist
    ini_files = glob.glob(dapsrc+'/python/mangadap/config/reduction_assessments/*.ini')
    if len(ini_files) == 0:
        raise IOError('Could not find any configuration files in {0} !'.format(
                      dapsrc+'/python/mangadap/config/reduction_assessments'))

    # Build the list of library definitions
    assessment_methods = []
    for f in ini_files:
        # Read the config file
        cnfg = ConfigParser(environ, allow_no_value=True, interpolation=ExtendedInterpolation())
        cnfg.read(f)
        # Ensure it has the necessary elements to define the template
        # library
        def_range, def_par, def_response = validate_reduction_assessment_config(cnfg)
        in_vacuum = False if 'in_vacuum' not in cnfg.options('default') \
                        else cnfg['default'].getboolean('in_vacuum')
#        covariance = None if 'covariance' not in cnfg.options('default') else \
#                        cnfg['default']['covariance']
                        
        if def_range:
            waverange = [ None if 'None' in e else float(e.strip()) \
                            for e in cnfg['default']['wave_limits'].split(',') ]
            if not in_vacuum:
                waverange = airtovac(waverange)
            assessment_methods += [ ReductionAssessmentDef(key=cnfg['default']['key'],
                                                           waverange=waverange,
                                            covariance=cnfg['default'].getboolean('covariance'))
                                  ]
        else:
            raise ValueError('Cannot use par_file or response_function_file yet!')

    # Check the keywords of the libraries are all unique
    if len(numpy.unique( numpy.array([ method['key'] for method in assessment_methods ]) )) \
            != len(assessment_methods):
        raise KeyError('Reduction assessment method keywords are not all unique!')

    # Return the default list of assessment methods
    return assessment_methods


class ReductionAssessment:
    r"""

    Object used to perform and store a number of assessments of a DRP
    file needed for handling of the data by the DAP.  These assessments
    need only be done once per DRP data file.

    See :func:`compute` for the provided data.

    Args:

        method_key (str): Keyword selecting the assessment method to
            use.
        drpf (:class:`mangadap.drpfits.DRPFits`): DRP file (object) to
            use for the assessments.
        pa (float): (**Optional**) On-sky position angle of the major
            axis used to calculate elliptical, semi-major-axis
            coordinates, defined as the angle from North through East
            and denoted :math:`\phi_0`.  Default is 0.0.
        ell (float): (**Optional**) Ellipticity defined as
            :math:`\varepsilon=1-b/a`, based on the semi-minor to
            semi-major axis ratio (:math:`b/a`) of the isophotal ellipse
            used to calculate elliptical, semi-major-axis coordinates.
            Default is 0.0.
        method_list (list): (**Optional**) List of
            :class:`ReductionAssessmentDef` objects that define the
            parameters required to perform the assessments of the DRP
            file.  The *method_key* must select one of these objects.
        dapver (str): (**Optional**) DAP version, which is used to
            define the default DAP analysis path.  Default is defined by
            :func:`mangadap.config.defaults.default_dap_version`
        analysis_path (str): (**Optional**) The path to the top level
            directory containing the DAP output files for a given DRP
            and DAP version.  Default is defined by
            :func:`mangadap.config.defaults.default_analysis_path`.
        directory_path (str): (**Optional**) The exact path for the
            output file.  Default is defined by
            :func:`mangadap.config.defaults.default_dap_reference_path`.
        output_file (str): (**Optional**) The name of the file for the
            computed assessments.  The full path of the output file will
            be :attr:`directory_path`/:attr:`output_file`.  Default is
            defined by
            :func:`mangadap.config.defaults.default_reduction_assessments_file`.
        hardcopy (bool): (**Optional**) Flag to write the data to a fits
            file.  Default is True.
        clobber (bool): (**Optional**) If the output file already
            exists, this will force the assessments to be redone and the
            output file to be overwritten.  Default is False.
        verbose (int): (**Optional**) Verbosity level.  See
            :func:`mangadap.survey.manga_dap`.

    Attributes:
        version (str): Version number
        method (str): Keyword of the selected method to use.
        drpf (:class:`mangadap.drpfits.DRPFits`): DRP file (object) with
            which the template library is associated for analysis
        pa (float): On-sky position angle of the major axis used to
            calculate elliptical, semi-major-axis coordinates, defined
            as the angle from North through East and denoted
            :math:`\phi_0`.
        ell (float): Ellipticity defined as :math:`\varepsilon=1-b/a`,
            based on the semi-minor to semi-major axis ratio
            (:math:`b/a`) of the isophotal ellipse used to calculate
            elliptical, semi-major-axis coordinates.
        directory_path (str): The exact path for the output file.
            Default is defined by
            :func:`mangadap.config.defaults.default_dap_reference_path`.
        output_file (str): The name of the file for the
            computed assessments.  The full path of the output file will
            be :attr:`directory_path`/:attr:`output_file`.  Default is
            defined by
            :func:`mangadap.config.defaults.default_reduction_assessments_file`.
        hardcopy (bool): Flag to keep a hardcopy of the data by writing
            the data to a fits file.
        hdu (`astropy.io.fits.hdu.hdulist.HDUList`_): HDUList with the
            data, with columns as described above.
        correlation (:class:`mangadap.util.covariance.Covariance`):
            Covariance matrix for the mean flux measurements, if
            calculated.
        verbose (int): Verbosity level.  See
            :func:`mangadap.survey.manga_dap`.

    """

    def __init__(self, method_key, drpf, pa=0.0, ell=0.0, method_list=None, dapsrc=None,
                 dapver=None, analysis_path=None, directory_path=None, output_file=None,
                 hardcopy=True, clobber=False, verbose=0):
                 
        self.version = '1.0'
        self.verbose = verbose

        # Define the method properties
        self.method = None
        self._define_method(method_key, method_list=method_list, dapsrc=dapsrc)

        # Set in compute via _set_paths
        self.drpf = None

        # Define the output directory and file
        self.directory_path = None      # Set in _set_paths
        self.output_file = None
        self.hardcopy = None

        # Initialize the objects used in the assessments
        self.pa = None
        self.ell = None
        self.hdu = None
        self.correlation = None

        # Run the assessments of the DRP file
        self.compute(drpf, pa=pa, ell=ell, dapver=dapver, analysis_path=analysis_path,
                     directory_path=directory_path, output_file=output_file, hardcopy=hardcopy,
                     clobber=clobber, verbose=verbose)


    def __del__(self):
        """
        Deconstruct the data object by ensuring that the fits file is
        properly closed.
        """
        if self.hdu is None:
            return
        self.hdu.close()
        self.hdu = None


    def __getitem__(self, key):
        return self.hdu[key]


    def _define_method(self, method_key, method_list=None, dapsrc=None):
        """
        Select the assessment method from the provided list.  Used to set
        :attr:`method` and :attr:`methodparset`; see
        :func:`mangadap.proc.util._select_proc_method`.

        Args:
            method_key (str): Keyword of the selected method.  Available
                methods are provided by
                :func:`available_reduction_assessments`
            method_list (list): (**Optional**) List of
                :class:`ReductionAssessmentDef' objects that define the
                parameters required to assess the reduced data.
            dapsrc (str): (**Optional**) Root path to the DAP source
                directory.  If not provided, the default is defined by
                :func:`mangadap.config.defaults.default_dap_source`.
        """
        self.method = _select_proc_method(method_key, ReductionAssessmentDef,
                                                method_list=method_list,
                                                available_func=available_reduction_assessments,
                                                dapsrc=dapsrc)


    def _set_paths(self, directory_path, dapver, analysis_path, output_file):
        """
        Set the I/O path to the processed template library.  Used to set
        :attr:`directory_path` and :attr:`output_file`.  If not
        provided, the defaults are set using, respectively,
        :func:`mangadap.config.defaults.default_dap_reference_path` and
        :func:`mangadap.config.defaults.default_dap_file_name`.

        Args:
            directory_path (str): The exact path to the DAP reduction
                assessments file.  See :attr:`directory_path`.
            dapver (str): DAP version.
            analysis_path (str): The path to the top-level directory
                containing the DAP output files for a given DRP and DAP
                version.
            output_file (str): The name of the file with the reduction assessments.
                See :func:`compute`.
        """
        # Set the output directory path
        self.directory_path = default_dap_reference_path(plate=self.drpf.plate,
                                                         drpver=self.drpf.drpver,
                                                         dapver=dapver,
                                                         analysis_path=analysis_path) \
                                        if directory_path is None else str(directory_path)

        # Set the output file
        self.output_file = default_dap_file_name(self.drpf.plate, self.drpf.ifudesign,
                                                 self.drpf.mode, self.method['key']) \
                                        if output_file is None else str(output_file)

    def _per_spectrum_dtype(self):
        r"""
        Construct the record array data type for the output fits
        extension.
        """
        return [ ('DRP_INDEX',numpy.int,(numpy.asarray(tuple(self.drpf.spatial_index)).shape[1],)),
                 ('SKY_COO',numpy.float,(2,)),
                 ('ELL_COO',numpy.float,(2,)),
                 ('FGOODPIX',numpy.float),
                 ('MINEQMAX',numpy.uint8),
                 ('SIGNAL',numpy.float),
                 ('VARIANCE',numpy.float),
                 ('SNR',numpy.float)
               ]

#    def _correl_dtype(self):
#        r"""
#        Construct the record array data type for the output fits
#        extension.
#        """
#        return [ ('INDX', numpy.int, (2,) ),
#                 ('CORREL', numpy.float)
#               ]

    def file_name(self):
        """Return the name of the output file."""
        return self.output_file


    def file_path(self):
        """Return the full path to the output file."""
        if self.directory_path is None or self.output_file is None:
            return None
        return os.path.join(self.directory_path, self.output_file)


    def info(self):
        return self.hdu.info()


    def compute(self, drpf, pa=None, ell=None, dapver=None, analysis_path=None, directory_path=None,
                output_file=None, hardcopy=True, clobber=False, verbose=0):
        r"""

        Compute and output the main data products.  The list of HDUs
        are:
            - ``PRIMARY`` : Empty apart from the header information.
            - ``SPECTRUM`` : Extension with the main, per-spectrum
              measurements; see below.
            - ``COVAR`` : The second extension for the correlation
              matrix between the ``SIGNAL`` measurements provided in the
              ``SPECTRUM`` extension.  The format of this extension is
              identical to the nominal output of the
              :class:`mangadap.util.covariance.Covariance` object; see
              :func:`mangadap.util.covariance.Covariance.write`.

        The ``SPECTRUM`` extension contains the following columns:
            - ``DRP_INDEX`` : Array coordinates in the DRP file; see
              :attr:`mangadap.drpfits.DRPFits.spatial_index`.  For RSS
              files, this is a single integer; for CUBE files, it is a
              vector of two integers.
            - ``SKY_COO`` : On-sky X and Y coordinates.  Coordinates are
              sky-right offsets from the object center; i.e., positive X
              is along the direction of positive right ascension.  For
              CUBE files, this is the position of the spaxel.  For RSS
              files, this is the flux-weighted mean over the wavelength
              range of the calculation.
            - ``ELL_COO`` : Elliptical (semi-major axis) radius and
              azimuth angle from N through East with respect to the
              photometric position angle; based on the provided
              ellipticity parameters.
            - ``FGOODPIX`` : Fraction of good pixels in each spectrum.
            - ``MINEQMAX`` : Flag that min(flux) = max(flux) in the
              spectrum; i.e., the spaxel has no data.
            - ``SIGNAL``, ``VARIANCE``, ``SNR`` : Per pixel means of the
              flux, flux variance, and signal-to-noise.  The
              ``VARIANCE`` and ``SNR`` columns use the inverse variance
              provided by the DRP directly, even if the covariance
              matrix is returned.  See
              :func:`mangadap.drpfits.DRPFits.flux_stats`.

        Args:
            drpf (:class:`mangadap.drpfits.DRPFits`): DRP file (object)
                to use for the assessments.
            pa (float): (**Optional**) On-sky position angle of the
                major axis used to calculate elliptical, semi-major-axis
                coordinates, defined as the angle from North through
                East and denoted :math:`\phi_0`.  Default is 0.0.
            ell (float): (**Optional**) Ellipticity defined as
                :math:`\varepsilon=1-b/a`, based on the semi-minor to
                semi-major axis ratio (:math:`b/a`) of the isophotal
                ellipse used to calculate elliptical, semi-major-axis
                coordinates.  Default is 0.0.
            dapver (str): (**Optional**) DAP version, which is used to
                define the default DAP analysis path.  Default is
                defined by
                :func:`mangadap.config.defaults.default_dap_version`
            analysis_path (str): (**Optional**) The path to the top
                level directory containing the DAP output files for a
                given DRP and DAP version.  Default is defined by
                :func:`mangadap.config.defaults.default_analysis_path`.
            directory_path (str): (**Optional**) The exact path for the
                output file.  Default is defined by
                :func:`mangadap.config.defaults.default_dap_reference_path`.
            output_file (str): (**Optional**) The name of the file for
                the computed assessments.  The full path of the output
                file will be :attr:`directory_path`/:attr:`output_file`.
                Default is defined by
                :func:`mangadap.config.defaults.default_reduction_assessments_file`.
            hardcopy (bool): (**Optional**) Flag to write the data to a
                fits file.  Default is True.
            clobber (bool): (**Optional**) If the output file already
                exists, this will force the assessments to be redone and
                the output file to be overwritten.  Default is False.
            verbose (int): (**Optional**) Verbosity level.  See
                :func:`mangadap.survey.manga_dap`.
    
        Raises:
            ValueError: Raise if no DRPFits object is provided or if
                the output file is undefined.
        """
        if drpf is None:
            raise ValueError('Must provide DRP file object to compute assessments.')
        if not isinstance(drpf, DRPFits):
            raise TypeError('Must provide a valid DRPFits object!')
        if drpf.hdu is None:
            warnings.warn('DRP file previously unopened.  Reading now.')
            drpf.open_hdu()
        self.drpf = drpf

        # Reset the output paths if necessary
        self._set_paths(directory_path, dapver, analysis_path, output_file)
        print(self.file_path())
        # Check that the path for or to the file is defined
        ofile = self.file_path()
        if ofile is None:
            raise ValueError('File path for output file is undefined!')
        # If the file already exists, and not clobbering, just read the
        # file
        if os.path.isfile(ofile) and not clobber:
            self.hdu = fits.open(ofile)
            self.correlation = Covariance(source=self.hdu, primary_ext='COVAR')
            self.pa = self.hdu['PRIMARY'].header['PA']
            if pa is not None and self.pa != pa:
                warnings.warn('Provided position angle different from available file; set ' \
                              'clobber=True to overwrite.')
            self.ell = self.hdu['PRIMARY'].header['ELL']
            if ell is not None and self.ell != ell:
                warnings.warn('Provided ellipticity different from available file; set ' \
                              'clobber=True to overwrite.')
            return

        # (Re)Initialize some of the attributes
        if pa is not None:
            self.pa = pa
        if ell is not None:
            self.ell = ell

        # Initialize the record array for the SPECTRUM extension
        spectrum_data = init_record_array(drpf.nspec, self._per_spectrum_dtype())
        spectrum_data['DRP_INDEX'] = numpy.asarray(tuple(drpf.spatial_index))
        spectrum_data['SKY_COO'][:,0], spectrum_data['SKY_COO'][:,1] \
                = drpf.mean_sky_coordinates(waverange=self.method['waverange'], offset=True)

#        pyplot.scatter(spectrum_data['SKY_COO'][:,0], spectrum_data['SKY_COO'][:,1], marker='.',
#                       s=30, color='k', lw=0)
#        pyplot.show()

        coord_conversion = SemiMajorAxisCoo(xc=0, yc=0, rot=0, pa=self.pa, ell=self.ell)
        spectrum_data['ELL_COO'][:,0], spectrum_data['ELL_COO'][:,1] \
            = coord_conversion.polar(spectrum_data['SKY_COO'][:,0], spectrum_data['SKY_COO'][:,1])

#        pyplot.scatter(spectrum_data['ELL_COO'][:,0], spectrum_data['ELL_COO'][:,1], marker='.',
#                       s=30, color='k', lw=0)
#        pyplot.show()
       
        flux = drpf.copy_to_masked_array(flag=['DONOTUSE', 'FORESTAR'])
        spectrum_data['FGOODPIX'] = numpy.sum(numpy.invert(numpy.ma.getmaskarray(flux)),axis=1) \
                                            / flux.shape[1]
       
        frange = numpy.ma.max(flux, axis=1)-numpy.ma.min(flux, axis=1)
        spectrum_data['MINEQMAX'] = (numpy.invert(numpy.ma.getmaskarray(frange))) \
                                        & (numpy.ma.absolute(frange) < 1e-10)
#        print(spectrum_data['MINEQMAX'])
#        print(drpf.nspec, numpy.sum(spectrum_data['MINEQMAX'] & (spectrum_data['FGOODPIX'] > 0.8)))

#        srt = numpy.argsort(spectrum_data['FGOODPIX'])
#        grw = numpy.arange(len(srt))/len(srt)
#        pyplot.step(spectrum_data['FGOODPIX'][srt], grw, color='k')
#        pyplot.show()

        spectrum_data['SIGNAL'], spectrum_data['VARIANCE'], spectrum_data['SNR'], self.correlation \
                = drpf.flux_stats(waverange=self.method['waverange'],
                                  covar=self.method['covariance'], correlation=True)

#        if correlation is not None:
#            correlation.show()
#
#        pyplot.scatter(spectrum_data['SIGNAL'], spectrum_data['VARIANCE'], marker='.', color='k',
#                       s=30)
#        pyplot.plot([0,2], numpy.square(numpy.array([0,2])/50.), color='r')
#        pyplot.show()

        # Construct header
        hdr = fits.Header()
        hdr['PA'] = (self.pa, 'Isophotal position angle')
        hdr['ELL'] = (self.ell, 'Isophotal ellipticity (1-b/a)')

        # Get the covariance columns; pulled directly from ../util/covariance.py
        if self.method['covariance']:
            cov_hdr = fits.Header()
            indx_col, covar_col, var_col, plane_col = self.correlation.binary_columns(hdr=cov_hdr)
            if plane_col is not None:
                raise ValueError('Correlation matrices should only be 2D in ReductionAssessments;' \
                                 ' code inconsistency!')

        # Get the main extension columns and construct the HDUList
        spectrum_cols = [ fits.Column(name=n, format=rec_to_fits_type(spectrum_data[n]),
                                      array=spectrum_data[n]) for n in spectrum_data.dtype.names ]
        self.hdu = fits.HDUList([ fits.PrimaryHDU(header=hdr),
                                  fits.BinTableHDU.from_columns( spectrum_cols, name='SPECTRUM') ])

        # Add the covariance information
        if self.method['covariance']:
            self.hdu += [ fits.BinTableHDU.from_columns( ([ indx_col, covar_col ] \
                                                            if var_col is None else \
                                                            [ indx_col, var_col, covar_col ]),
                                                        name='COVAR', header=cov_hdr) ]

        # Write the file
        if not os.path.isdir(self.directory_path):
            os.makedirs(self.directory_path)
        self.hardcopy = hardcopy
        if self.hardcopy:
            write_hdu(self.hdu, ofile, clobber=clobber, checksum=True)

        

