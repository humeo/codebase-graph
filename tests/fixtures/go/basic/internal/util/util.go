package util

type Service struct{}

type Alias = Service

type Reader interface {
	Read()
}

func Parse() {}

func (s *Service) Run() {}
