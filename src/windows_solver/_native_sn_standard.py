"""Generalized Sasaki-Nakamura radial determinant solver for spin minus two."""
from __future__ import annotations
import cmath, hashlib, math, os, json
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from ._native_spin_weighted_spheroidal import spherical_A, sep_const
from ._native_gsn_equations import radial_coordinate_coefficients

_declared_infinity_series_cache = os.environ.get('GSN_INFINITY_SERIES_CACHE')
_declared_infinity_series_cache_sha256 = os.environ.get(
    'GSN_INFINITY_SERIES_CACHE_SHA256'
)
if not _declared_infinity_series_cache:
    raise RuntimeError(
        'GSN_INFINITY_SERIES_CACHE must name the canonical coefficient cache'
    )
INFINITY_SERIES_CACHE_PATH = Path(_declared_infinity_series_cache)
if not INFINITY_SERIES_CACHE_PATH.is_file():
    raise RuntimeError(
        f'canonical GSN infinity-series cache is absent: '
        f'{INFINITY_SERIES_CACHE_PATH}'
    )


@lru_cache(maxsize=1)
def _infinity_series_cache():
    raw = INFINITY_SERIES_CACHE_PATH.read_bytes()
    if _declared_infinity_series_cache_sha256 is not None:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != _declared_infinity_series_cache_sha256:
            raise RuntimeError('GSN infinity-series cache digest mismatch code=31')
    return json.loads(raw)


@lru_cache(maxsize=None)
def _compiled_infinity_series(a: float, m: int):
    key=f'm={int(m)};a={float(a):.15g}'
    record=_infinity_series_cache()['records'].get(key)
    if record is None:
        raise ValueError(f'undeclared infinity-series parameter pair {key}')
    output=[]
    for name in ('F','U'):
        item=record[name]
        numerator=[compile(x,f'{INFINITY_SERIES_CACHE_PATH}:{key}:{name}:numerator','eval')
                   for x in item['numerator_coefficients_ascending']]
        denominator=[compile(x,f'{INFINITY_SERIES_CACHE_PATH}:{key}:{name}:denominator','eval')
                     for x in item['denominator_coefficients_ascending']]
        output.append((numerator,denominator))
    return tuple(output)

def _series_ratio(num,den,N):
    num=np.asarray(num,complex);den=np.asarray(den,complex)
    scale=max(1.,np.max(np.abs(num)),np.max(np.abs(den)));tol=1e-14*scale
    vn=next((i for i,c in enumerate(num) if abs(c)>tol),len(num));vd=next((i for i,c in enumerate(den) if abs(c)>tol),len(den))
    if vn==len(num):return np.zeros(N,complex)
    if vd==len(den):raise ZeroDivisionError
    sh=vn-vd
    if sh<0:raise ValueError('singular series ratio')
    n=num[vn:];d=den[vd:];inv=np.zeros(N,complex);inv[0]=1/d[0]
    for k in range(1,N):inv[k]=-sum(d[j]*inv[k-j] for j in range(1,min(k,len(d)-1)+1))/d[0]
    out=np.zeros(N,complex)
    for k in range(N-sh):out[k+sh]=sum(n[j]*inv[k-j] for j in range(max(0,k-N+1),min(k,len(n)-1)+1))
    return out

def _smul(A,B,L):
    out=np.zeros(L,complex)
    for k in range(L):out[k]=sum(A[j]*B[k-j] for j in range(max(0,k-len(B)+1),min(k,len(A)-1)+1))
    return out

def _Dr(T,L):
    out=np.zeros(L,complex)
    for k in range(min(len(T),L-1)):out[k+1]=-k*T[k]
    return out

def _rstar(r,a):
    rt=cmath.sqrt(1-a*a);rp=1+rt;rm=1-rt
    return r+2*rp/(rp-rm)*cmath.log((r-rp)/2)-2*rm/(rp-rm)*cmath.log((r-rm)/2)

class StandardSN:
    def __init__(
        self,
        a,
        l,
        m,
        R0=55.,
        K=14,
        pad=18,
        *,
        outer_angle=0.0,
        bridge_radius=None,
        horizon_order=28,
        horizon_cauchy_sample_count=256,
        integration_relative_tolerance=2e-10,
        integration_absolute_tolerance=2e-12,
        real_maximum_step=.2,
        complex_path_maximum_step=.01,
    ):
        self.a=float(a);self.l=int(l);self.m=int(m);self.R0=float(R0);self.K=int(K);self.pad=int(pad)
        self.outer_angle=float(outer_angle)
        self.bridge_radius=float(self.R0 if bridge_radius is None else bridge_radius)
        self.horizon_order=int(horizon_order)
        self.horizon_cauchy_sample_count=int(horizon_cauchy_sample_count)
        self.integration_relative_tolerance=float(integration_relative_tolerance)
        self.integration_absolute_tolerance=float(integration_absolute_tolerance)
        self.real_maximum_step=float(real_maximum_step)
        self.complex_path_maximum_step=float(complex_path_maximum_step)
        if (
            self.R0 <= 0
            or self.K < 1
            or self.horizon_order < 1
            or self.horizon_cauchy_sample_count < 2 * (self.horizon_order + 1)
        ):
            raise ValueError('invalid GSN seed protocol')
        if self.bridge_radius <= 0 or self.bridge_radius > self.R0:
            raise ValueError('invalid GSN bridge radius')
        if self.integration_relative_tolerance <= 0 or self.integration_absolute_tolerance <= 0:
            raise ValueError('invalid GSN integration tolerances')
        if self.real_maximum_step <= 0 or self.complex_path_maximum_step <= 0:
            raise ValueError('invalid GSN integration step controls')
        rt=math.sqrt(max(0.0,1-self.a*self.a));self.rp=1+rt;self.rm=1-rt;self.OmH=self.a/(2*self.rp) if self.a else 0.0
        self._pfn=lambda r,w,lam: radial_coordinate_coefficients(self.a,self.m,w,lam,r)[0]
        self._qfn=lambda r,w,lam: radial_coordinate_coefficients(self.a,self.m,w,lam,r)[1]
        self._asym=_compiled_infinity_series(self.a,self.m)
        self.A0=spherical_A(-2,self.l,self.m)
    def wfac(self,r):return (r*r-2*r+self.a*self.a)/(r*r+self.a*self.a)
    def lambda_phys(self,omega):
        c=self.a*omega;A=complex(sep_const(-2,c,self.m,self.l,self.l+self.pad));return A+c*c-2*self.m*c,A
    def _coeff(self,pair,omega,lam):
        fn,fd=pair; values={'omega':omega,'lam':lam}
        return ([complex(eval(f,{'__builtins__':{}},values)) for f in fn],
                [complex(eval(f,{'__builtins__':{}},values)) for f in fd])
    def asym_seed(self,omega,lam,direction=1,radius=None,include_phase=True):
        R=self.R0 if radius is None else radius; sigma=1 if direction>=0 else -1
        L=self.K+5;NF,DF=self._coeff(self._asym[0],omega,lam);NU,DU=self._coeff(self._asym[1],omega,lam);Fser=_series_ratio(NF,DF,L);User=_series_ratio(NU,DU,L)
        Aser=_series_ratio([1,-2,self.a*self.a],[1,0,self.a*self.a],L);Sl=np.zeros(L,complex);Sl[0]=1
        def Eser(series):
            DS=_Dr(series,L);ADS=_smul(Aser,DS,L)
            return -omega*omega*series+2j*sigma*omega*ADS+_smul(Aser,_Dr(ADS,L),L)-_smul(Fser,1j*sigma*omega*series+ADS,L)-_smul(User,series,L)
        for n in range(1,self.K+1):
            Sl[n]=0;r1=Eser(Sl)[n+1]
            basis=np.zeros(L,complex);basis[n]=1
            linear=Eser(basis)[n+1]
            if not np.isfinite(linear.real) or not np.isfinite(linear.imag) or abs(linear)==0:
                raise FloatingPointError('singular GSN infinity-series recurrence')
            Sl[n]=-r1/linear
        u0=1/R;Sv=sum(Sl[k]*u0**k for k in range(self.K+1));Svr=sum(Sl[k]*(-k)*u0**(k+1) for k in range(1,self.K+1));wr=self.wfac(R)
        Xr=(1j*sigma*omega/wr)*Sv+Svr
        if include_phase:
            ph=cmath.exp(1j*sigma*omega*_rstar(R,self.a));Sv*=ph;Xr*=ph
        return Sv,Xr
    def _horizon_series(self,omega,lam,order=28,radius_frac=0.2,nsamp=256):
        # Cauchy-extract radius-scaled Taylor coefficients of x*p and x^2*q.
        # Keeping P_n=p_n*rad^n and C_n=c_n*rad^n avoids under/overflow at
        # the manuscript order 180, especially near extremality.
        gap=self.rp-self.rm; rad=min(0.05,max(1e-5,radius_frac*gap))
        nsamp=max(int(nsamp),2*(int(order)+1))
        th=2*np.pi*np.arange(nsamp)/nsamp; z=rad*np.exp(1j*th); rr=self.rp+z
        pbar=z*np.asarray(self._pfn(rr,omega,lam),complex)
        qbar=z*z*np.asarray(self._qfn(rr,omega,lam),complex)
        ph=np.exp(-1j*np.outer(np.arange(order+1),th))
        pc=(ph@pbar)/nsamp
        qc=(ph@qbar)/nsamp
        p=omega-self.m*self.OmH; A=(self.rp*self.rp+self.a*self.a)/(self.rp-self.rm);rho=-1j*p*A
        c=np.zeros(order+1,complex);c[0]=1
        for n in range(1,order+1):
            den=(rho+n)*(rho+n-1)+pc[0]*(rho+n)+qc[0]
            c[n]=-sum((pc[n-j]*(rho+j)+qc[n-j])*c[j] for j in range(n))/den
        return rho,c,pc,qc,rad,nsamp
    def horizon_seed(self,omega,lam,radius=None,order=None):
        if order is None: order=self.horizon_order
        if radius is None: radius=self.rp+min(1e-4,0.02*(self.rp-self.rm))
        x=radius-self.rp;rho,c,pc,qc,rad,nsamp=self._horizon_series(
            omega,
            lam,
            order=order,
            nsamp=self.horizon_cauchy_sample_count,
        )
        t=x/rad
        S=sum(c[k]*t**k for k in range(order+1));Sp=sum(k*c[k]*t**(k-1) for k in range(1,order+1))/rad
        X=x**rho*S;Xr=x**rho*(rho*S/x+Sp)
        p=omega-self.m*self.OmH;A=(self.rp*self.rp+self.a*self.a)/(self.rp-self.rm)
        C=self.rp-A*math.log(2)-2*self.rm/(self.rp-self.rm)*math.log((self.rp-self.rm)/2)
        norm=cmath.exp(-1j*p*C)
        return norm*X,norm*Xr
    def integrate_real(self,omega,lam,r0,r1,y0,rtol=None,atol=None,max_step=None,dense=False):
        if rtol is None: rtol=self.integration_relative_tolerance
        if atol is None: atol=self.integration_absolute_tolerance
        if max_step is None: max_step=self.real_maximum_step
        def ode(r,y):return np.array([y[1],-complex(self._pfn(r,omega,lam))*y[1]-complex(self._qfn(r,omega,lam))*y[0]],complex)
        sol=solve_ivp(ode,(r0,r1),np.asarray(y0,complex),method='DOP853',rtol=rtol,atol=atol,max_step=max_step,dense_output=dense)
        if not sol.success:raise RuntimeError(sol.message)
        return sol
    def integrate_path(self,omega,lam,z0,z1,y0,rtol=None,atol=None,max_step=None):
        if rtol is None: rtol=self.integration_relative_tolerance
        if atol is None: atol=self.integration_absolute_tolerance
        if max_step is None: max_step=self.complex_path_maximum_step
        dz=z1-z0
        def ode(s,y):
            r=z0+dz*s
            return dz*np.array([y[1],-complex(self._pfn(r,omega,lam))*y[1]-complex(self._qfn(r,omega,lam))*y[0]],complex)
        sol=solve_ivp(ode,(0,1),np.asarray(y0,complex),method='DOP853',rtol=rtol,atol=atol,max_step=max_step)
        if not sol.success:raise RuntimeError(sol.message)
        return sol.y[:,-1]
    def horizon_at(self,omega,r=6.0):
        lam,_=self.lambda_phys(omega);rh=self.rp+min(2e-4,0.02*(self.rp-self.rm));y0=self.horizon_seed(omega,lam,rh)
        sol=self.integrate_real(omega,lam,rh,r,y0)
        return sol.y[:,-1],lam
    def outer_seed_point(self):
        return self.R0*cmath.exp(1j*self.outer_angle)
    def outgoing_real_seed(self,omega,lam):
        outer=self.outer_seed_point(); y0=self.asym_seed(omega,lam,+1,outer,True)
        if abs(outer-self.bridge_radius) <= 1e-15:
            return self.bridge_radius,np.asarray(y0,complex)
        return self.bridge_radius,self.integrate_path(omega,lam,outer,self.bridge_radius,y0)
    def outgoing_at(self,omega,r=6.0):
        lam,_=self.lambda_phys(omega);start,y0=self.outgoing_real_seed(omega,lam);sol=self.integrate_real(omega,lam,start,r,y0)
        return sol.y[:,-1],lam
    def determinant(self,omega,r=6.0):
        hi,lam=self.horizon_at(omega,r);up,_=self.outgoing_at(omega,r)
        wf=self.wfac(r)
        # W in r_* orientation
        return wf*(hi[0]*up[1]-hi[1]*up[0])
    def qnef(self,omega,r=6.0,h=2e-6):
        hi,lam=self.horizon_at(omega,r);up,_=self.outgoing_at(omega,r)
        Aout=hi[0]/up[0]
        Dp=(self.determinant(omega+h,r)-self.determinant(omega-h,r))/(2*h)
        return 1j*Aout/Dp,Aout,Dp
    def outgoing_dense_to_horizon(self,omega,rmin,rmax=None):
        lam,_=self.lambda_phys(omega)
        if rmax is None:
            rmax,y0=self.outgoing_real_seed(omega,lam)
        else:
            y0=self.asym_seed(omega,lam,+1,rmax,True)
        return self.integrate_real(omega,lam,rmax,rmin,y0,rtol=5e-10,atol=5e-12,max_step=.1,dense=True),lam

def _anti_stokes_amplitudes(self,omega,bridge=10.0,Rabs=35.0):
    lam,_=self.lambda_phys(omega);rh=self.rp+min(2e-4,0.02*(self.rp-self.rm));y0=self.horizon_seed(omega,lam,rh)
    sol=self.integrate_real(omega,lam,rh,bridge,y0,rtol=1e-10,atol=1e-12,max_step=.1)
    yb=sol.y[:,-1]
    ang=-cmath.phase(omega)
    Rc=Rabs*cmath.exp(1j*ang)
    yc=self.integrate_path(omega,lam,bridge,Rc,yb,rtol=1e-10,atol=1e-12,max_step=.005)
    bout=np.asarray(self.asym_seed(omega,lam,+1,Rc,True),complex)
    bin_=np.asarray(self.asym_seed(omega,lam,-1,Rc,True),complex)
    amps=np.linalg.solve(np.column_stack([bout,bin_]),yc)
    return amps[0],amps[1]
StandardSN.anti_stokes_amplitudes=_anti_stokes_amplitudes

def _qnef_as(self,omega,h=1e-6):
    ao,ai=self.anti_stokes_amplitudes(omega)
    aip=self.anti_stokes_amplitudes(omega+h)[1]
    aim=self.anti_stokes_amplitudes(omega-h)[1]
    return ao/(2*omega*(aip-aim)/(2*h)),ao,ai
StandardSN.qnef_as=_qnef_as


# Compatibility aliases used across the validated code paths.
GSN = StandardSN
SNStandard = StandardSN
